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
    has_slides: bool = False
    summary: str | None = None
    summary_status: str | None = None
    adr_draft: str | None = None
    adr_status: str | None = None
    adr_template: str | None = None
    adr_confidence: str | None = None
    adr_generated_at: str | None = None
    created_at: str
    updated_at: str


class SourceUrlCreate(BaseModel):
    url: HttpUrl


class SourceRename(BaseModel):
    title: str


class SourceLink(BaseModel):
    """ソース親子リンク。"""
    id: str
    notebook_id: str
    parent_source_id: str
    child_source_id: str
    relation: str  # 'presentation' | 'manual'
    meta: dict | None
    created_at: str


class SlideUtteranceItem(BaseModel):
    """スライド資料の該当ページで発言された録音チャンク 1 件(逆引き)。"""
    child_source_id: str
    child_title: str | None
    chunk_id: str
    start_ms: int | None
    end_ms: int | None
    speaker: str | None
    text: str


class SlideUtterancePage(BaseModel):
    """ページ単位にグループ化した発言一覧。"""
    page: int
    items: list[SlideUtteranceItem]
