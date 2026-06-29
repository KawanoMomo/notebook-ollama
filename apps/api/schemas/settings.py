from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class GenerationSettingsSchema(BaseModel):
    context_budget_ratio: float
    response_budget_tokens: int


class RetrievalSettingsSchema(BaseModel):
    top_k: int
    top_k_max: int
    min_history_turns: int


class OllamaSettingsSchema(BaseModel):
    endpoint: str
    default_model: str
    embedding_model: str
    embedding_dim: int | None = None
    # Phase 1 acceleration backend selection. Default "auto" preserves
    # existing behavior (BackendPlanner picks ollama-cuda on RTX 2080 Ti).
    runtime_backend: Literal["auto", "ollama-cuda"] = "auto"
    text_embed_backend: Literal["auto", "ollama-bge-m3-cpu"] = "auto"


class OllamaSettingsUpdate(BaseModel):
    default_model: str


class AudioSettingsSchema(BaseModel):
    mic_device_index: int | None = None
    system_device_index: int | None = None
    whisper_model: str
    device: Literal["cuda", "cpu"]
    compute_type: Literal["float16", "int8_float16", "int8"]
    live_caption_default: bool
    agc_enabled: bool
    diarization_enabled: bool
    max_speakers: int | None = None
    voiceprint_naming: bool
    name_inference_llm: bool
    name_threshold: float
    storage_format: Literal["aac", "opus", "mp3", "wav"]
    storage_bitrate_kbps: int
    keep_audio: bool
    auto_title: bool
    # Phase 1 acceleration backend selection. Default "auto" preserves
    # existing behavior (BackendPlanner picks faster-whisper-cuda / sherpa-onnx-cpu
    # / sherpa-onnx-cpu on RTX 2080 Ti).
    transcriber_backend: Literal[
        "auto", "faster-whisper-cuda", "faster-whisper-cpu"
    ] = "auto"
    diarizer_backend: Literal["auto", "sherpa-onnx-cpu"] = "auto"
    speaker_embed_backend: Literal["auto", "sherpa-onnx-cpu"] = "auto"


class AppSettingsSchema(BaseModel):
    ollama: OllamaSettingsSchema
    generation: GenerationSettingsSchema
    retrieval: RetrievalSettingsSchema
    audio: AudioSettingsSchema


class EmbeddingSwitchRequest(BaseModel):
    model: str


# ---------------------------------------------------------------------------
# Sprint 3 / Task 3.5 — read-only Acceleration tab schemas
# ---------------------------------------------------------------------------


class HwProfileSchema(BaseModel):
    """Wire-format projection of ``core.accel.profile.HwProfile``.

    Field renames vs. the dataclass:

    * ``has_cuda`` -> ``cuda`` (matches the Acceleration tab vocabulary —
      operators talk about "CUDA available", not "has_cuda boolean").

    Dropped vs. the dataclass:

    * ``vendor`` / ``cuda_device_count`` — the AccelerationPanel.svelte UI
      derives display sections from ``cuda`` / ``igpu`` / ``npu`` directly,
      so these are not part of the read-only contract.
    """

    cpu_brand: str
    cuda: bool
    dgpu: str | None
    igpu: str | None
    npu: str | None
    vram_mb: int | None
    ryzen_ai_gen: int | None
    openvino_devices: list[str]
    has_directml: bool


class BackendPlanSchema(BaseModel):
    """Wire-format projection of ``core.accel.plan.BackendPlan``.

    The ``hw_profile`` field on the dataclass is intentionally dropped here —
    the response carries ``hw_profile`` as a sibling key, so re-emitting it
    nested inside ``backend_plan`` would duplicate the data.
    """

    stt_id: str
    diarize_id: str
    llm_id: str
    text_embed_id: str
    reason: str


class AccelerationResponseSchema(BaseModel):
    """Response body for ``GET /api/settings/acceleration``."""

    hw_profile: HwProfileSchema
    backend_plan: BackendPlanSchema
    is_phase1_implementable: bool
