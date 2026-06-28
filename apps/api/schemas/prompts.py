"""Prompt injection 設計の API スキーマ。

設計: docs/specs/2026-06-26-prompt-injection-design.md §4.5
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class FixedPromptSlotOut(BaseModel):
    title: str
    body: str
    icon_url: str | None = None


class DropdownPromptOut(BaseModel):
    id: str
    title: str
    body: str


class PromptsOut(BaseModel):
    fixed: list[FixedPromptSlotOut]
    dropdown: list[DropdownPromptOut]


class FixedPromptSlotUpdate(BaseModel):
    title: str = Field(max_length=100)
    body: str = Field(max_length=10_000)


class DropdownPromptCreate(BaseModel):
    title: str = Field(max_length=100)
    body: str = Field(max_length=10_000)


class DropdownPromptUpdate(DropdownPromptCreate):
    pass


class DropdownOrderUpdate(BaseModel):
    ids: list[str]
