from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class DevSettingsSchema(BaseModel):
    enabled: bool
    log_capacity_bytes: int


class DevSettingsUpdate(BaseModel):
    """PUT /settings/dev の入力。容量は 1MB..200MB へクランプして採用(§9.2 E7)。"""

    enabled: bool
    log_capacity_bytes: int | None = None


class GenerationSettingsSchema(BaseModel):
    context_budget_ratio: float
    response_budget_tokens: int
    auto_continue_max: int


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
    request_timeout_seconds: float = 600.0
    chat_read_timeout_seconds: float = 600.0
    vision_model: str = ""


class OllamaSettingsUpdate(BaseModel):
    default_model: str


class VisionModelUpdate(BaseModel):
    model: str  # 空文字列で未設定に戻す


class OllamaTimeoutsUpdate(BaseModel):
    # 24 時間以上は受け付けない(誤入力ガード)。最小は 5 秒。
    request_timeout_seconds: float = Field(ge=5, le=86400)
    chat_read_timeout_seconds: float = Field(ge=5, le=86400)


class GenerationSettingsUpdate(BaseModel):
    """PUT /settings/generation の入力。

    response_budget_tokens は num_predict にそのまま渡る応答上限。
    思考モデルは thinking もこの予算を消費するため下限は 64 とし、
    誤入力ガードとして 32768 を上限にする。

    auto_continue_max は done_reason=length 検知時の自動継続最大回数
    (issue #22)。0 で無効、上限5は num_ctx 押し出しの安全弁。
    """

    response_budget_tokens: int = Field(ge=64, le=32768)
    context_budget_ratio: float | None = Field(default=None, gt=0.1, lt=0.95)
    auto_continue_max: int | None = Field(default=None, ge=0, le=5)


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


class CrashReportSettingsSchema(BaseModel):
    """``core.crash_reporter.settings.CrashReportSettings`` の HTTP 表現。

    spec §7.3 / Sprint 3 のオプトイン三値モデルをそのまま受け渡す:
    - ``enabled``: ``None`` = 未決定 / ``True`` = オプトイン / ``False`` = 明示拒否
    - ``auto_prompt``: クラッシュ検知時に自動でオプトインダイアログを出すか
    - ``opted_in_at``: オプトイン (または明示的オプトアウト) を記録した UTC 時刻
    """

    enabled: bool | None = None
    auto_prompt: bool = True
    opted_in_at: datetime | None = None


class CrashReportSettingsUpdate(BaseModel):
    """``PUT /api/settings/crash-report`` の部分更新ペイロード。

    全フィールドが optional (= ``None`` を許容しつつ未指定との区別を
    ``model_fields_set`` で行う) なので、UI からは「変更したいフィールドだけ」
    を送れば残りは現値が保たれる。``enabled=None`` を明示的に再設定したい
    用途は無い (オプトイン状態を「未決定」に戻す意味が無い) ため、
    `enabled` のみ ``bool`` に絞り、未指定なら現値保持とする。
    """

    enabled: bool | None = None
    auto_prompt: bool | None = None
    opted_in_at: datetime | None = None


class VoiceInputSettingsSchema(BaseModel):
    """``core.config.VoiceInputSettings`` の HTTP 表現(GET/PUT 共用)。"""

    mode: Literal["off", "push_to_talk", "hands_free"] = "push_to_talk"
    ptt_key: str = Field(default="Space", min_length=1, max_length=64)


class VisualSettingsSchema(BaseModel):
    """``core.config.VisualSettings`` の HTTP 表現(Stage 3 視覚埋め込み)。"""

    embedding_model: str
    search_enabled: bool


class VisualSettingsUpdate(BaseModel):
    """PUT /settings/visual の入力。トグルできるのは search_enabled のみ。"""

    search_enabled: bool


class AppSettingsSchema(BaseModel):
    ollama: OllamaSettingsSchema
    generation: GenerationSettingsSchema
    retrieval: RetrievalSettingsSchema
    audio: AudioSettingsSchema
    crash_report: CrashReportSettingsSchema | None = None
    voice_input: VoiceInputSettingsSchema | None = None
    dev: DevSettingsSchema | None = None
    visual: VisualSettingsSchema


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
