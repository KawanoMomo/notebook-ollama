from __future__ import annotations

from pydantic import BaseModel, Field


class NotebookCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    default_model: str | None = None


class NotebookUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    default_model: str | None = None


class Notebook(BaseModel):
    id: str
    name: str
    description: str | None
    default_model: str | None
    created_at: str
    updated_at: str
    source_count: int = 0
