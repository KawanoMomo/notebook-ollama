from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


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
    request_timeout_seconds: float = 600.0
    chat_read_timeout_seconds: float = 600.0


class OllamaSettingsUpdate(BaseModel):
    default_model: str


class OllamaTimeoutsUpdate(BaseModel):
    # 24 時間以上は受け付けない(誤入力ガード)。最小は 5 秒。
    request_timeout_seconds: float = Field(ge=5, le=86400)
    chat_read_timeout_seconds: float = Field(ge=5, le=86400)


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


class AppSettingsSchema(BaseModel):
    ollama: OllamaSettingsSchema
    generation: GenerationSettingsSchema
    retrieval: RetrievalSettingsSchema
    audio: AudioSettingsSchema


class EmbeddingSwitchRequest(BaseModel):
    model: str
