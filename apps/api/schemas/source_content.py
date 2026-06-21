from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class DocumentSection(BaseModel):
    heading_path: str | None = None
    page: int | None = None
    text: str


class RecordingSegment(BaseModel):
    ord: int
    text: str
    start_ms: int | None = None
    end_ms: int | None = None
    speaker: str | None = None


class DocumentContent(BaseModel):
    kind: Literal["document"] = "document"
    sections: list[DocumentSection]


class RecordingContent(BaseModel):
    kind: Literal["recording"] = "recording"
    segments: list[RecordingSegment]


class SpeakerRename(BaseModel):
    from_label: str
    to_label: str
