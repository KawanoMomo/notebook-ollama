"""``BackendFactory`` — Phase 1 CUDA + CPU builder for resolved ``BackendPlan``s.

Sprint 3 / Task 3.2 of `docs/superpowers/plans/2026-06-29-igpu-npu-acceleration.md`.

The Factory is the gate between "Planner picked an id" (pure data, see
``core.accel.planner.BackendPlanner.plan``) and "concrete object I can call".
Phase 1 ships five Phase 1-implementable ids only — every other id raises
``NotImplementedError`` with an explicit "Phase 2" message so the
Acceleration tab and startup log can surface a clean "not yet shipped"
diagnostic.

The split between Planner (data) and Factory (gate) is deliberate: it keeps
the Planner pure / table-testable across every HW profile, and pushes the
"can we actually build this?" decision into one tiny module that is trivial
to grep and audit.

Implementable ids (mirrored in
``core.accel.plan.PHASE1_IMPLEMENTABLE_IDS``; Phase 1.5 = spec addendum
2026-08-02):

* STT:         ``faster-whisper-cuda``, ``faster-whisper-cpu``
* DIARIZE:     ``sherpa-onnx-cpu``
* LLM:         ``ollama-cuda`` (also serves the CPU-only host — Ollama
               auto-degrades when no GPU is visible), ``ollama-vulkan``
               (same builder — the Vulkan backend lives in the Ollama
               server), ``openai-compat`` (``OpenAICompatClient`` at
               ``openai_compat_endpoint``)
* TEXT_EMBED:  ``ollama-bge-m3-cpu`` (Ollama NaN workaround pins CUDA
               hosts to CPU embed; #13572 closed without root fix),
               ``openai-compat-embed`` (independent embed endpoint —
               addendum M asymmetric wiring)

Phase 2 ids (``openvino-whisper-igpu`` / ``openvino-whisper-npu`` /
``amd-whispercpp-vulkan`` / ``openvino-bge-m3-igpu`` /
``openvino-bge-m3-npu``) all raise ``NotImplementedError`` whose message
contains the substring ``"Phase 2"``.

INVARIANT (verified by ``test_factory.py``): builders do NOT modify any
constructor signature of the existing concrete classes (``Transcriber``,
``SherpaDiarizer``, ``OllamaGateway``). The Factory wraps them transparently
so Phase 2 can swap the concrete class behind the same id without touching
any call site.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from core.accel.plan import BackendPlan
from core.ollama.client import OllamaClient
from core.ollama.gateway import OllamaGateway

if TYPE_CHECKING:
    from core.config import AudioSettings, OllamaSettings


# ---------------------------------------------------------------------------
# TextEmbedder shape (Phase 1 internal)
# ---------------------------------------------------------------------------


class _TextEmbedderLike(Protocol):
    """Phase 1 text-embedder shape — a bound model name + async ``embed``.

    Phase 2 OpenVINO embedders (``openvino-bge-m3-igpu`` / ``-npu``) implement
    the same protocol so call sites don't change when the backend swaps.
    """

    @property
    def model(self) -> str: ...

    async def embed(self, text: str) -> list[float]: ...


class _OllamaTextEmbedder:
    """``TEXT_EMBED`` adapter — ``OllamaGateway`` with the embed model name bound.

    Today's code does ``await gateway.embed(model=cfg.embedding_model, text=...)``
    everywhere. The wrapper preserves that exact behaviour while giving the
    Factory a uniform "TextEmbedder-like" return shape that Phase 2 OpenVINO
    embedders can implement without touching every call site.
    """

    def __init__(self, gateway: OllamaGateway, model: str) -> None:
        self._gateway = gateway
        self._model = model

    @property
    def model(self) -> str:
        return self._model

    @property
    def gateway(self) -> OllamaGateway:
        """Expose the underlying gateway — Phase 1 DI keeps a single shared instance."""
        return self._gateway

    async def embed(self, text: str) -> list[float]:
        return await self._gateway.embed(model=self._model, text=text)


# ---------------------------------------------------------------------------
# Phase 2 error helper
# ---------------------------------------------------------------------------


def _phase2_not_implemented(role: str, backend_id: str) -> NotImplementedError:
    """Build the canonical Phase 2 "not yet implementable" exception.

    The message contains the substring ``"Phase 2"`` so callers (and the
    Acceleration tab) can pattern-match on it without parsing the id name.
    """
    return NotImplementedError(
        f"Phase 2 backend {backend_id!r} (role={role}) not yet implemented; "
        "current Phase 1 only supports CUDA + CPU paths"
    )


# ---------------------------------------------------------------------------
# BackendFactory
# ---------------------------------------------------------------------------


class BackendFactory:
    """Build Phase 1 concrete backend instances from a ``BackendPlan``.

    Each builder switches on the matching id in the plan and constructs the
    existing concrete class with no constructor-signature changes (existing
    transcriber / diarizer / gateway tests stay green). Phase 2 ids raise
    ``NotImplementedError("... Phase 2 ...")``.

    The Factory is stateless; construct once per process or per call — both
    are valid. The DI wiring (Task 3.4) constructs a single shared instance.
    """

    # ------------------------------------------------------------------
    # STT (transcriber)
    # ------------------------------------------------------------------

    def build_transcriber(
        self, plan: BackendPlan, audio_cfg: AudioSettings
    ) -> Any:
        """Build the STT transcriber chosen by the Planner.

        * ``faster-whisper-cuda`` → ``Transcriber(model_size=audio_cfg.whisper_model,
          device="cuda", compute_type=audio_cfg.compute_type)``.
        * ``faster-whisper-cpu`` → ``Transcriber(model_size=audio_cfg.whisper_model,
          device="cpu", compute_type="int8")``. ``compute_type`` is fixed to
          ``"int8"`` on CPU: ``float16`` is not supported on CPU and the
          existing CPU fallback path in ``Transcriber._fallback_to_cpu``
          already hard-codes ``"int8"`` — staying consistent here keeps the
          two code paths interchangeable.
        * Any other id → ``NotImplementedError("Phase 2 ...")``.
        """
        # Lazy import — keeps ``faster_whisper`` out of the factory's import
        # cost on hosts that never construct a transcriber (tests, CI).
        from core.recording.transcriber import Transcriber

        sid = plan.stt_id
        if sid == "faster-whisper-cuda":
            return Transcriber(
                model_size=audio_cfg.whisper_model,
                device="cuda",
                compute_type=audio_cfg.compute_type,
            )
        if sid == "faster-whisper-cpu":
            return Transcriber(
                model_size=audio_cfg.whisper_model,
                device="cpu",
                compute_type="int8",
            )
        raise _phase2_not_implemented("STT", sid)

    # ------------------------------------------------------------------
    # DIARIZE
    # ------------------------------------------------------------------

    def build_diarizer(
        self, plan: BackendPlan, audio_cfg: AudioSettings
    ) -> Any:
        """Build the diarizer — v1 is CPU-only on every host.

        ``sherpa-onnx-cpu`` → existing ``SherpaDiarizer``. The diarizer model
        paths must be resolved by the caller (DI layer / Task 3.4); the
        Factory doesn't know ``data_dir`` so it refuses to invent defaults
        — ``audio_cfg.diarizer_segmentation_model`` and
        ``audio_cfg.diarizer_embedding_model`` must be non-empty.
        """
        from core.recording.diarizer import SherpaDiarizer

        did = plan.diarize_id
        if did == "sherpa-onnx-cpu":
            seg = audio_cfg.diarizer_segmentation_model
            emb = audio_cfg.diarizer_embedding_model
            if not seg or not emb:
                raise ValueError(
                    "diarizer model paths must be resolved before BackendFactory."
                    "build_diarizer (got segmentation_model="
                    f"{seg!r}, embedding_model={emb!r})"
                )
            num_clusters = (
                audio_cfg.max_speakers if audio_cfg.max_speakers is not None else -1
            )
            return SherpaDiarizer(
                segmentation_model=Path(seg),
                embedding_model=Path(emb),
                threshold=audio_cfg.diarizer_threshold,
                num_clusters=num_clusters,
            )
        raise _phase2_not_implemented("DIARIZE", did)

    # ------------------------------------------------------------------
    # LLM
    # ------------------------------------------------------------------

    def build_llm_gateway(
        self, plan: BackendPlan, ollama_cfg: OllamaSettings
    ) -> OllamaGateway:
        """Build the LLM gateway (Ollama HTTP or OpenAI-compatible HTTP).

        * ``ollama-cuda`` / ``ollama-vulkan`` → official Ollama at
          ``ollama_cfg.endpoint``. The two ids share one builder because the
          Vulkan backend lives inside the Ollama *server* process (addendum
          K1: default-enabled since v0.13) — from this app's side the only
          difference is which accelerator the server picked, surfaced by the
          id for diagnostics. ``ollama-cuda`` also serves the CPU-only host
          (Ollama auto-degrades when no GPU is visible).
        * ``openai-compat`` → ``OllamaGateway`` wrapping an
          ``OpenAICompatClient`` at ``ollama_cfg.openai_compat_endpoint``
          (addendum L). The endpoint must be configured — an empty string
          raises ``ValueError`` with a clear message instead of producing a
          gateway that can only fail at request time.

        Phase 2 ids raise ``NotImplementedError``.
        """
        lid = plan.llm_id
        if lid in ("ollama-cuda", "ollama-vulkan"):
            return self._build_ollama_gateway(ollama_cfg)
        if lid == "openai-compat":
            endpoint = ollama_cfg.openai_compat_endpoint
            if not endpoint:
                raise ValueError(
                    "runtime_backend='openai-compat' requires "
                    "ollama.openai_compat_endpoint to be set in settings.json "
                    "(e.g. \"http://localhost:8080\" for llama-server)"
                )
            return self._build_openai_compat_gateway(ollama_cfg, endpoint)
        raise _phase2_not_implemented("LLM", lid)

    # ------------------------------------------------------------------
    # TEXT_EMBED
    # ------------------------------------------------------------------

    def build_text_embedder(
        self,
        plan: BackendPlan,
        ollama_cfg: OllamaSettings,
        *,
        gateway: OllamaGateway | None = None,
    ) -> _TextEmbedderLike:
        """Build the text embedder, optionally reusing a pre-built gateway.

        Phase 1 routes everything through ``ollama-bge-m3-cpu`` — the CPU
        embed path is the workaround for upstream Ollama #13572 NaN bug, and
        is the only embedder shipped in Phase 1. The returned wrapper exposes
        ``await embed(text) -> list[float]`` with the model name bound; Phase 2
        OpenVINO embedders will implement the same shape so call sites don't
        change when the backend swaps.

        ``gateway`` (kw-only) controls whether to reuse an existing
        :class:`OllamaGateway` or construct a fresh one:

        * ``None`` (default) → build a fresh gateway with
          :meth:`_build_ollama_gateway`. Keeps the Factory usable as a
          stand-alone utility (unit tests, MCP server, ad-hoc scripts).
        * pre-built ``OllamaGateway`` → reuse it. The DI layer
          (``apps.api.dependencies.build_context``) passes the LLM-side
          gateway through here so the runtime has exactly ONE
          ``OllamaGateway`` (and therefore one httpx client) per process.
        """
        tid = plan.text_embed_id
        if tid == "ollama-bge-m3-cpu":
            # Reuse the passed-in gateway ONLY when the LLM side is also an
            # Ollama transport. When plan.llm_id == "openai-compat" the passed
            # gateway wraps an OpenAICompatClient — reusing it would silently
            # redirect bge-m3 embeds to the compat server (wrong server, wrong
            # NaN workaround). Build a dedicated Ollama gateway instead.
            if gateway is None or plan.llm_id not in (
                "ollama-cuda",
                "ollama-vulkan",
            ):
                gateway = self._build_ollama_gateway(ollama_cfg)
            return _OllamaTextEmbedder(gateway, ollama_cfg.embedding_model)
        if tid == "openai-compat-embed":
            # Addendum M(非対称構成): 埋め込みは生成と独立したエンドポイント。
            # 専用 URL(openai_compat_embed_endpoint)が無ければ LLM 側の
            # openai_compat_endpoint を流用する。渡された ``gateway``(Ollama
            # 用)は再利用しない — 経路が違うので必ず専用 gateway を建てる。
            # embedding_options(num_gpu=0)は Ollama 固有の NaN 回避であり、
            # OpenAI 互換 API には対応概念が無いため引き渡さない。
            endpoint = (
                ollama_cfg.openai_compat_embed_endpoint
                or ollama_cfg.openai_compat_endpoint
            )
            if not endpoint:
                raise ValueError(
                    "text_embed_backend='openai-compat-embed' requires "
                    "ollama.openai_compat_embed_endpoint (or "
                    "ollama.openai_compat_endpoint) to be set in settings.json"
                )
            embed_gateway = self._build_openai_compat_gateway(ollama_cfg, endpoint)
            return _OllamaTextEmbedder(embed_gateway, ollama_cfg.embedding_model)
        raise _phase2_not_implemented("TEXT_EMBED", tid)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _build_ollama_gateway(self, ollama_cfg: OllamaSettings) -> OllamaGateway:
        """Construct an ``OllamaGateway`` with the canonical Phase 1 wiring.

        Mirrors ``apps.api.dependencies.build_context`` so that the Factory
        path is bit-identical to the legacy DI path until Task 3.4 cuts the
        DI layer over to the Factory. Two callers (``build_llm_gateway`` and
        ``build_text_embedder``) share this helper.
        """
        client = OllamaClient(
            endpoint=ollama_cfg.endpoint,
            timeout=ollama_cfg.request_timeout_seconds,
            chat_read_timeout=ollama_cfg.chat_read_timeout_seconds,
        )
        return OllamaGateway(
            client=client,
            embedding_options=ollama_cfg.embedding_options or None,
        )

    def _build_openai_compat_gateway(
        self, ollama_cfg: OllamaSettings, endpoint: str
    ) -> OllamaGateway:
        """Construct an ``OllamaGateway`` over an ``OpenAICompatClient``.

        The gateway layer (chat/embed serialization locks, generate helper)
        is transport-agnostic — only the ``_ClientLike`` implementation
        changes (addendum L). Timeouts reuse the same Ollama settings so a
        slow local server gets the same generous budget.
        ``embedding_options`` (``num_gpu=0``) is the Ollama-specific NaN
        workaround with no OpenAI-API counterpart — never forwarded here.
        """
        from core.ollama.openai_compat import OpenAICompatClient

        client = OpenAICompatClient(
            endpoint=endpoint,
            api_key=ollama_cfg.openai_compat_api_key,
            timeout=ollama_cfg.request_timeout_seconds,
            chat_read_timeout=ollama_cfg.chat_read_timeout_seconds,
        )
        return OllamaGateway(client=client, embedding_options=None)


__all__ = ["BackendFactory"]
