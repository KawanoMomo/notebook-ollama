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


class _TransformersBackend:
    """実モデルを抱える内部バックエンド。CUDA不可ならCPUへフォールバック(spec §7)。

    Qwen3-VL-Embedding の正規APIは sentence-transformers
    (`library_name: sentence-transformers`、モデルカードの Usage 参照)。
    素の AutoModel/AutoProcessor では VLM の forward が input_ids を要求して
    画像単独の埋め込みが組めない(実機ゲートで確認)ため、ST 経由で呼ぶ。
    """

    def __init__(self, model_name: str) -> None:
        import torch
        from sentence_transformers import SentenceTransformer

        self._torch = torch
        self._device = "cuda" if torch.cuda.is_available() else "cpu"
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
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._model_name = model_name
        self._idle = idle_unload_seconds
        self._monotonic = monotonic
        self._backend: Any | None = None
        self._last_used: float = 0.0
        self._lock = asyncio.Lock()

    @property
    def loaded(self) -> bool:
        return self._backend is not None

    def _load_backend(self) -> Any:
        return _TransformersBackend(self._model_name)

    async def _ensure_loaded(self) -> Any:
        async with self._lock:
            if self._backend is None:
                # ロードは重い(数秒〜)のでスレッドへ逃がす
                self._backend = await asyncio.to_thread(self._load_backend)
            self._last_used = self._monotonic()
            return self._backend

    async def embed_image(self, *, png: bytes) -> list[float]:
        backend = await self._ensure_loaded()
        vec = await asyncio.to_thread(backend.embed_image, png)
        self._last_used = self._monotonic()
        return vec

    async def embed_text(self, *, text: str) -> list[float]:
        backend = await self._ensure_loaded()
        vec = await asyncio.to_thread(backend.embed_text, text)
        self._last_used = self._monotonic()
        return vec

    def maybe_unload_if_idle(self) -> bool:
        if self._backend is None:
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
