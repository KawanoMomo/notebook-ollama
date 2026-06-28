from __future__ import annotations

from pydantic import BaseModel


class StartRecording(BaseModel):
    live_caption: bool = True
    mic_device_index: int | None = None
    system_device_index: int | None = None


class RecordingStarted(BaseModel):
    recording_id: str
    source_id: str
    status: str
    live_caption: bool
