"""プロンプト設定の Pydantic モデル群。

固定スロットは常に長さ 3、プルダウンは任意件数(最大は store 層で制限)。
未設定は空文字列で表現する(None は使わない、既存 settings の流儀)。

設計: docs/specs/2026-06-26-prompt-injection-design.md §3
"""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class FixedPromptSlot(BaseModel):
    """固定ボタン 1 スロット。長さ 3 のリストで常に保持する。

    未設定の判定は store/route 側で title.strip() と body.strip() 双方で行う。
    アイコン画像は data_dir/prompt-icons/<filename> に置き、ファイル名のみを保持。
    """

    title: str = Field(default="", max_length=100)
    body: str = Field(default="", max_length=10_000)
    icon_filename: str | None = None


class DropdownPrompt(BaseModel):
    """プルダウン候補 1 件。並び替え/編集/削除は id をキーにする。"""

    id: str
    title: str = Field(max_length=100)
    body: str = Field(max_length=10_000)


class PromptsSettings(BaseModel):
    """`AppSettings.prompts` に乗る一式。

    `fixed` は常に長さ 3、`dropdown` は順序が表示順そのもの。
    """

    fixed: list[FixedPromptSlot] = Field(
        default_factory=lambda: [FixedPromptSlot() for _ in range(3)]
    )
    dropdown: list[DropdownPrompt] = Field(default_factory=list)

    @field_validator("fixed")
    @classmethod
    def _exactly_three_slots(cls, v: list[FixedPromptSlot]) -> list[FixedPromptSlot]:
        if len(v) != 3:
            raise ValueError("fixed must contain exactly 3 slots")
        return v
