from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


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
