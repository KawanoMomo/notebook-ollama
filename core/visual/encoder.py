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
    """実モデルを抱える内部バックエンド。実験枠: モデルAPIの妥当性は
    実機ゲートで検証する。CUDA不可ならCPUへフォールバック(spec §7)。"""

    def __init__(self, model_name: str) -> None:
        import torch
        from transformers import AutoModel, AutoProcessor

        self._torch = torch
        self._device = "cuda" if torch.cuda.is_available() else "cpu"
        dtype = torch.float16 if self._device == "cuda" else torch.float32
        log.info("visual_encoder_loading", model=model_name, device=self._device)
        self._processor = AutoProcessor.from_pretrained(model_name, trust_remote_code=True)
        self._model = AutoModel.from_pretrained(
            model_name, torch_dtype=dtype, trust_remote_code=True
        ).to(self._device)
        self._model.eval()

    def _pool(self, outputs: Any) -> list[float]:
        # 埋め込み専用モデルは pooled/text_embeds 相当を返すことが多い。
        # 無ければ last_hidden_state の平均でフォールバックし、L2正規化する。
        t = getattr(outputs, "pooler_output", None)
        if t is None:
            t = outputs.last_hidden_state.mean(dim=1)
        t = t[0].float()
        t = t / (t.norm() + 1e-12)
        return t.tolist()

    def embed_image(self, png: bytes) -> list[float]:
        import io

        from PIL import Image

        image = Image.open(io.BytesIO(png)).convert("RGB")
        inputs = self._processor(images=image, return_tensors="pt").to(self._device)
        with self._torch.no_grad():
            outputs = self._model(**inputs)
        return self._pool(outputs)

    def embed_text(self, text: str) -> list[float]:
        inputs = self._processor(text=[text], return_tensors="pt", padding=True).to(self._device)
        with self._torch.no_grad():
            outputs = self._model(**inputs)
        return self._pool(outputs)

    def close(self) -> None:
        self._model = None
        self._processor = None
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
