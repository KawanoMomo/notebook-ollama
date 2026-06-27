"""プロンプト設定の永続化 + CRUD ヘルパ。

`settings.json` の `prompts` キーに JSON 直列化して保存する。他セクション
(`audio` / `ollama` 等)とは独立して書き換えるため、`settings_store.save_section`
を再利用して粒度を 1 セクションに固定する。

設計: docs/specs/2026-06-26-prompt-injection-design.md §3
"""
from __future__ import annotations

import uuid
from pathlib import Path

from pydantic import ValidationError

from core.exceptions import AppError, ErrorCode
from core.logging import get_logger
from core.prompts.models import DropdownPrompt, FixedPromptSlot, PromptsSettings
from core.settings_store import load_overrides, save_section

log = get_logger("prompts.store")

_DROPDOWN_LIMIT = 100
_TITLE_MAX = 100
_BODY_MAX = 10_000


# --- load / save ----------------------------------------------------------


def load_prompts(data_dir: Path) -> PromptsSettings:
    """settings.json から prompts セクションをロードする。

    キー欠落・型不正・JSON 破損のいずれでも既定 (空 3 スロット + 空配列) に
    フォールバックして起動を止めない。これは audio/ollama セクションと同じ流儀。
    """
    raw = load_overrides(data_dir).get("prompts")
    if not isinstance(raw, dict):
        return PromptsSettings()
    try:
        return PromptsSettings.model_validate(raw)
    except ValidationError:
        log.warning("prompts_overrides_invalid")
        return PromptsSettings()


def save_prompts(data_dir: Path, prompts: PromptsSettings) -> None:
    """prompts セクションを settings.json に書き戻す。他セクションは保持。"""
    save_section(data_dir, "prompts", prompts.model_dump())


# --- 固定スロット --------------------------------------------------------


def _check_slot(slot: int) -> None:
    if slot not in (0, 1, 2):
        raise AppError(
            ErrorCode.INPUT_INVALID, "slot_index must be 0, 1, or 2"
        )


def set_fixed(
    data_dir: Path,
    slot: int,
    *,
    title: str,
    body: str,
) -> PromptsSettings:
    """固定スロットの title/body を上書きする(icon_filename は維持)。"""
    _check_slot(slot)
    _check_text_len(title, body)
    p = load_prompts(data_dir)
    current = p.fixed[slot]
    p.fixed[slot] = FixedPromptSlot(
        title=title, body=body, icon_filename=current.icon_filename
    )
    save_prompts(data_dir, p)
    return p


def clear_fixed(data_dir: Path, slot: int) -> PromptsSettings:
    """固定スロットを完全に空にする(アイコン参照も消す)。"""
    _check_slot(slot)
    p = load_prompts(data_dir)
    p.fixed[slot] = FixedPromptSlot()
    save_prompts(data_dir, p)
    return p


def set_fixed_icon(
    data_dir: Path, slot: int, *, icon_filename: str | None
) -> PromptsSettings:
    """固定スロットの icon_filename だけ差し替える(title/body は維持)。"""
    _check_slot(slot)
    p = load_prompts(data_dir)
    current = p.fixed[slot]
    p.fixed[slot] = FixedPromptSlot(
        title=current.title,
        body=current.body,
        icon_filename=icon_filename,
    )
    save_prompts(data_dir, p)
    return p


# --- プルダウン CRUD -----------------------------------------------------


def add_dropdown(
    data_dir: Path, *, title: str, body: str
) -> DropdownPrompt:
    _check_text_len(title, body)
    p = load_prompts(data_dir)
    if len(p.dropdown) >= _DROPDOWN_LIMIT:
        raise AppError(
            ErrorCode.INPUT_INVALID,
            f"dropdown limit exceeded (max {_DROPDOWN_LIMIT})",
        )
    new_id = str(uuid.uuid4())
    new_item = DropdownPrompt(id=new_id, title=title, body=body)
    p.dropdown.append(new_item)
    save_prompts(data_dir, p)
    return new_item


def update_dropdown(
    data_dir: Path, prompt_id: str, *, title: str, body: str
) -> DropdownPrompt:
    _check_text_len(title, body)
    p = load_prompts(data_dir)
    for i, item in enumerate(p.dropdown):
        if item.id == prompt_id:
            updated = DropdownPrompt(id=item.id, title=title, body=body)
            p.dropdown[i] = updated
            save_prompts(data_dir, p)
            return updated
    raise AppError(
        ErrorCode.STORAGE_NOT_FOUND, f"dropdown prompt {prompt_id} not found"
    )


def delete_dropdown(data_dir: Path, prompt_id: str) -> PromptsSettings:
    p = load_prompts(data_dir)
    new_list = [d for d in p.dropdown if d.id != prompt_id]
    if len(new_list) == len(p.dropdown):
        raise AppError(
            ErrorCode.STORAGE_NOT_FOUND, f"dropdown prompt {prompt_id} not found"
        )
    p.dropdown = new_list
    save_prompts(data_dir, p)
    return p


def reorder_dropdown(data_dir: Path, ids: list[str]) -> PromptsSettings:
    """完全な順序を一括指定する。現状の id 集合と完全一致しなければ拒否。"""
    p = load_prompts(data_dir)
    current_ids = [d.id for d in p.dropdown]
    if sorted(ids) != sorted(current_ids):
        raise AppError(
            ErrorCode.INPUT_INVALID,
            "ids must contain exactly the current dropdown ids",
        )
    by_id = {d.id: d for d in p.dropdown}
    p.dropdown = [by_id[i] for i in ids]
    save_prompts(data_dir, p)
    return p


# --- helpers --------------------------------------------------------------


def _check_text_len(title: str, body: str) -> None:
    if len(title) > _TITLE_MAX:
        raise AppError(
            ErrorCode.INPUT_INVALID, f"title must be <= {_TITLE_MAX} chars"
        )
    if len(body) > _BODY_MAX:
        raise AppError(
            ErrorCode.INPUT_INVALID, f"body must be <= {_BODY_MAX} chars"
        )
