"""視覚埋め込みエンコーダ (Stage 3, spec §4/§7)。

Ollama は画像埋め込みに非対応のため transformers スタックで実行する
(ADRドラフト draft-2026-07-20-visual-embedding-ondemand-transformers)。
実モデル依存はこのファイルの _TransformersBackend に閉じ込める —
それ以外の全コードは VisualEncoder Protocol(Fake差し替え可能)にのみ依存する。
"""
from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Any, Protocol

from core.logging import get_logger

log = get_logger("visual.encoder")


def visual_extra_available() -> bool:
    """`uv sync --extra visual` 済みか(recording extraの503縮退と同型)。"""
    try:
        import torch  # noqa: F401
        import transformers  # noqa: F401
    except ImportError:
        return False
    return True


class VisualEncoder(Protocol):
    async def embed_image(self, *, png: bytes) -> list[float]: ...
    async def embed_text(self, *, text: str) -> list[float]: ...
    def unload(self) -> None: ...

    @property
    def device(self) -> str | None:
        """実際にモデルが載っているデバイス。未ロードなら None。

        呼び出し側(index_builder のクールダウン判定)が CPU 固有の安全弁を
        適用すべきかを決めるために使う。`torch.cuda.is_available()` は
        cuDNN のバージョン衝突下でも True を返す(ECN-005)ため、可用性ではなく
        実際のロード先を公開する。
        """
        ...


def _set_execution_speed_throttling(*, disable: bool) -> bool:
    """Windows の EcoQoS(効率モード)実行速度スロットリングを切り替える。

    バックグラウンドプロセスは EcoQoS で E-core に寄せられ、CPU推論の重い
    スレッドが E-coreクラスタを100%飽和させてブラウザ等の背景処理と競合する
    (実機観測 2026-07-26: torch 8スレッドが全てE-core 16〜23に張り付き)。
    disable=True で「速度を絞るな」とOSへ伝えると、Thread Director が重い
    スレッドをP-coreへ載せる。プロセス全体のアフィニティ固定と違い、他の
    軽いスレッドを巻き込まないヒントで済む。戻り値は成否(Windows以外・
    API失敗時は False、例外は出さない)。
    """
    import sys

    if sys.platform != "win32":
        return False
    try:
        import ctypes
        from ctypes import wintypes

        class _PowerThrottlingState(ctypes.Structure):
            _fields_ = [
                ("Version", ctypes.c_ulong),
                ("ControlMask", ctypes.c_ulong),
                ("StateMask", ctypes.c_ulong),
            ]

        PROCESS_POWER_THROTTLING_EXECUTION_SPEED = 0x1
        ProcessPowerThrottling = 4
        state = _PowerThrottlingState(
            1,  # PROCESS_POWER_THROTTLING_CURRENT_VERSION
            PROCESS_POWER_THROTTLING_EXECUTION_SPEED,
            # StateMask=0 → スロットリング無効(=P-core許可)。
            # 再有効化(restore)は StateMask にも速度ビットを立てる。
            0 if disable else PROCESS_POWER_THROTTLING_EXECUTION_SPEED,
        )
        # argtypes 明示は必須: 既定の c_int 変換では 64-bit HANDLE が壊れ、
        # ERROR_INVALID_HANDLE(6) で常に失敗する(実機で確認)。
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        kernel32.SetProcessInformation.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        kernel32.SetProcessInformation.restype = wintypes.BOOL
        ok = kernel32.SetProcessInformation(
            kernel32.GetCurrentProcess(),
            ProcessPowerThrottling,
            ctypes.byref(state),
            ctypes.sizeof(state),
        )
        if not ok:
            log.warning("visual_ecoqos_toggle_denied", last_error=ctypes.get_last_error())
        return bool(ok)
    except Exception:
        log.warning("visual_ecoqos_toggle_failed", exc_info=True)
        return False


class _TransformersBackend:
    """実モデルを抱える内部バックエンド。CUDA不可ならCPUへフォールバック(spec §7)。

    Qwen3-VL-Embedding の正規APIは sentence-transformers
    (`library_name: sentence-transformers`、モデルカードの Usage 参照)。
    素の AutoModel/AutoProcessor では VLM の forward が input_ids を要求して
    画像単独の埋め込みが組めない(実機ゲートで確認)ため、ST 経由で呼ぶ。
    """

    def __init__(
        self,
        model_name: str,
        *,
        cpu_threads: int = 0,
        prefer_performance_cores: bool = False,
    ) -> None:
        import torch
        from sentence_transformers import SentenceTransformer

        self._torch = torch
        self._device = "cuda" if torch.cuda.is_available() else "cpu"
        self._qos_disabled = False
        if self._device == "cpu" and cpu_threads > 0:
            # CPU埋め込みは全論理コアAVX全開の実質ストレステストになり、
            # マシンの電源/熱マージンを削る(実機で長時間構築中にBSODを観測)。
            # スレッド数を制限して消費電力を抑える安全弁(0=torch既定)。
            torch.set_num_threads(cpu_threads)
            log.info("visual_encoder_cpu_threads", threads=cpu_threads)
        if self._device == "cpu" and prefer_performance_cores:
            # 少数スレッドxP-core の分業プロファイル。バックエンド常駐中のみ
            # EcoQoS を解除し、close() で元に戻す。
            self._qos_disabled = _set_execution_speed_throttling(disable=True)
            log.info("visual_encoder_pcore_preference", applied=self._qos_disabled)
        # CPU は bfloat16(チェックポイントのネイティブdtype)でロードする。
        # float32 だと 2B で常駐約8GB+ロード時の型変換ピークが加わり、サーバー
        # プロセスの既存使用分と合わさって OOM 即死する(evaluator実機で確認:
        # 重みロード89%でプロセスごと消失、トレースバック無し)。bf16 なら
        # 常駐約4GB・変換なしで、単独スモークと同条件になる。
        dtype = torch.float16 if self._device == "cuda" else torch.bfloat16
        log.info("visual_encoder_loading", model=model_name, device=self._device)
        self._model = SentenceTransformer(
            model_name,
            device=self._device,
            model_kwargs={"torch_dtype": dtype},
        )

    @property
    def device(self) -> str:
        return self._device

    def embed_image(self, png: bytes) -> list[float]:
        import io

        from PIL import Image

        image = Image.open(io.BytesIO(png)).convert("RGB")
        vec = self._model.encode([image], normalize_embeddings=True)[0]
        return vec.tolist()

    def embed_text(self, text: str) -> list[float]:
        vec = self._model.encode([text], normalize_embeddings=True)[0]
        return vec.tolist()

    def close(self) -> None:
        self._model = None
        if self._device == "cuda":
            self._torch.cuda.empty_cache()
        if self._qos_disabled:
            # アンロード後はEcoQoSを元に戻す(常時P-core優先にしない —
            # アイドル時のサーバーは省電力スケジューリングで良い)
            _set_execution_speed_throttling(disable=False)
            self._qos_disabled = False


class TransformersVisualEncoder:
    """オンデマンドロード+アイドルアンロードのエンコーダ(spec §7)。

    ロードは初回 embed 呼び出し時。maybe_unload_if_idle() は外部(APIのジョブや
    リクエストの合間)から定期的に呼ばれる想定で、最終使用から
    idle_unload_seconds 経過していれば解放して True を返す。
    """

    def __init__(
        self,
        *,
        model_name: str,
        idle_unload_seconds: float = 300.0,
        cpu_threads: int = 0,
        prefer_performance_cores: bool = False,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._model_name = model_name
        self._idle = idle_unload_seconds
        self._cpu_threads = cpu_threads
        self._prefer_performance_cores = prefer_performance_cores
        self._monotonic = monotonic
        self._backend: Any | None = None
        self._last_used: float = 0.0
        self._lock = asyncio.Lock()
        # 実行中の embed 数。CPU では 1 回の埋め込みが idle_unload_seconds を
        # 超えうるため、開始時刻基準の idle 判定だけだと watchdog が計算中の
        # バックエンドを解放してしまう(実機でページ毎のロード/アンロード
        # スラッシングを観測)。in-flight 中は解放を禁止する。
        # 増減はイベントループ上でのみ行うためロック不要。
        self._active = 0

    @property
    def loaded(self) -> bool:
        return self._backend is not None

    @property
    def device(self) -> str | None:
        """バックエンドが載っているデバイス。未ロードなら None。

        アンロード後も None に戻る(次のロードで別デバイスになりうるため、
        古い値を持ち回らない)。
        """
        backend = self._backend
        return None if backend is None else backend.device

    def _load_backend(self) -> Any:
        return _TransformersBackend(
            self._model_name,
            cpu_threads=self._cpu_threads,
            prefer_performance_cores=self._prefer_performance_cores,
        )

    async def _ensure_loaded(self) -> Any:
        async with self._lock:
            if self._backend is None:
                # ロードは重い(数秒〜)のでスレッドへ逃がす
                self._backend = await asyncio.to_thread(self._load_backend)
            self._last_used = self._monotonic()
            return self._backend

    async def embed_image(self, *, png: bytes) -> list[float]:
        backend = await self._ensure_loaded()
        self._active += 1
        try:
            return await asyncio.to_thread(backend.embed_image, png)
        finally:
            self._active -= 1
            self._last_used = self._monotonic()

    async def embed_text(self, *, text: str) -> list[float]:
        backend = await self._ensure_loaded()
        self._active += 1
        try:
            return await asyncio.to_thread(backend.embed_text, text)
        finally:
            self._active -= 1
            self._last_used = self._monotonic()

    def maybe_unload_if_idle(self) -> bool:
        if self._backend is None or self._active > 0:
            return False
        if self._monotonic() - self._last_used < self._idle:
            return False
        self.unload()
        return True

    def unload(self) -> None:
        if self._backend is None:
            return
        log.info("visual_encoder_unloading", model=self._model_name)
        try:
            self._backend.close()
        finally:
            self._backend = None


async def run_idle_unload_watchdog(encoder: Any, *, interval_seconds: float = 60.0) -> None:
    """maybe_unload_if_idle を定期実行する常駐ループ(app lifespan から起動)。

    spec §7「オンデマンドロード+アイドルアンロード(既定5分)」の発火側。
    構築ジョブの finally だけでは、チャットのクエリでロードされたエンコーダが
    解放されず常駐し続ける(evaluator実機で確認: RSS 4GB台が居座る)。
    キャンセルされるまで無限ループし、1回の失敗でループを止めない。
    """
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            unload = getattr(encoder, "maybe_unload_if_idle", None)
            if callable(unload):
                unload()
        except Exception:
            log.warning("visual_unload_watchdog_failed", exc_info=True)
