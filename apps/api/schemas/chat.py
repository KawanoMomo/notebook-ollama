from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class EvidenceSpan(BaseModel):
    """引用チャンク本文の中で根拠になっている範囲(設計 §3.1.1)。"""

    answer_occurrence: int  # 0 起算
    ordinal: int | None = None  # 1 起算。第2段(embedding)では None
    start: int
    end: int
    quote: str
    method: Literal["lexical", "embedding", "quote"]


class ResolveSpansRequest(BaseModel):
    """第2段(埋め込み)の解決要求。どの [^n] 出現に対する解決かを指定する。"""

    answer_occurrence: int


class ResolveSpansResponse(BaseModel):
    spans: list[EvidenceSpan] = []
    method: str = "embedding"


class MessageInput(BaseModel):
    content: str = Field(min_length=1)
    source_ids: list[str] | None = None


class ContinueInput(BaseModel):
    """手動継続(issue #22)。元質問の source_ids は保存されないため FE が現選択を送る。"""

    source_ids: list[str] | None = None


class Message(BaseModel):
    id: str
    conversation_id: str
    role: str
    content: str
    citations: list[dict[str, Any]] = []
    model: str | None = None
    truncated: bool = False
    created_at: str


class Conversation(BaseModel):
    id: str
    notebook_id: str
    title: str | None
    created_at: str
    updated_at: str
