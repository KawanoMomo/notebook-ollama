from __future__ import annotations

from pydantic import BaseModel, Field


class StartRecording(BaseModel):
    live_caption: bool = True
    mic_device_index: int | None = None
    system_device_index: int | None = None
    # 発表モード: 発表対象スライドソース(kind pdf|pptx)。指定時は同一NB内で検証。
    presentation_source_id: str | None = None


class RecordingStarted(BaseModel):
    recording_id: str
    source_id: str
    status: str
    live_caption: bool
    presentation_source_id: str | None = None


class MarkerCreate(BaseModel):
    kind: str = Field(min_length=1, max_length=32)
    value: str = Field(min_length=1, max_length=256)


class ActiveRecording(BaseModel):
    recording_id: str
    source_id: str
    presentation_source_id: str | None = None
    last_page: int | None = None
    # 録音経過時間(ms)。リロード復帰時に FE が経過タイマーを再開する起点
    # (recordingStore.adopt)。マーカー at_ms と同じ epoch 基準でサーバー算出。
    elapsed_ms: int = 0
