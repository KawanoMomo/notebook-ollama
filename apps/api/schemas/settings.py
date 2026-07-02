from __future__ import annotations

from datetime import datetime
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


class AppSettingsSchema(BaseModel):
    ollama: OllamaSettingsSchema
    generation: GenerationSettingsSchema
    retrieval: RetrievalSettingsSchema
    audio: AudioSettingsSchema
    crash_report: CrashReportSettingsSchema | None = None


class EmbeddingSwitchRequest(BaseModel):
    model: str
