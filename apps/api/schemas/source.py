from __future__ import annotations

from pydantic import BaseModel, HttpUrl


class Source(BaseModel):
    id: str
    notebook_id: str
    kind: str
    title: str | None
    origin: str | None
    status: str
    error_msg: str | None
    bytes: int | None
    page_count: int | None
    chunk_count: int | None
    has_audio: bool = False
    created_at: str
    updated_at: str


class SourceUrlCreate(BaseModel):
    url: HttpUrl


class SourceRename(BaseModel):
    title: str
