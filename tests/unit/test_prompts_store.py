"""プロンプト設定の store/CRUD ユニットテスト。

設計: docs/specs/2026-06-26-prompt-injection-design.md §3, §7.1
"""
from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from core.exceptions import AppError, ErrorCode
from core.prompts.models import (
    DropdownPrompt,
    FixedPromptSlot,
    PromptsSettings,
)
from core.prompts.store import (
    add_dropdown,
    clear_fixed,
    delete_dropdown,
    load_prompts,
    reorder_dropdown,
    save_prompts,
    set_fixed,
    update_dropdown,
)

# --- 基本モデル -----------------------------------------------------------


def test_fixed_slot_defaults_to_empty_strings():
    s = FixedPromptSlot()
    assert s.title == ""
    assert s.body == ""
    assert s.icon_filename is None


def test_prompts_settings_defaults_to_3_empty_slots_and_empty_dropdown():
    p = PromptsSettings()
    assert len(p.fixed) == 3
    assert all(s.title == "" and s.body == "" for s in p.fixed)
    assert p.dropdown == []


def test_prompts_settings_rejects_non3_fixed_length():
    with pytest.raises(ValidationError):
        PromptsSettings(fixed=[FixedPromptSlot()], dropdown=[])


# --- load / save ----------------------------------------------------------


def test_load_prompts_returns_defaults_when_no_settings_file(tmp_path: Path):
    p = load_prompts(tmp_path)
    assert len(p.fixed) == 3
    assert p.dropdown == []


def test_load_prompts_returns_defaults_when_prompts_key_missing(tmp_path: Path):
    # settings.json は存在するが prompts キーが無い
    (tmp_path / "settings.json").write_text('{"audio": {}}', encoding="utf-8")
    p = load_prompts(tmp_path)
    assert len(p.fixed) == 3
    assert p.dropdown == []


def test_load_prompts_recovers_from_corrupt_prompts_block(tmp_path: Path):
    """型不正な prompts ブロックでも既定にフォールバックして起動を止めない。"""
    (tmp_path / "settings.json").write_text(
        '{"prompts": {"fixed": "not-a-list"}}', encoding="utf-8"
    )
    p = load_prompts(tmp_path)
    assert len(p.fixed) == 3


def test_save_and_load_round_trips(tmp_path: Path):
    saved = PromptsSettings(
        fixed=[
            FixedPromptSlot(title="要約", body="3行で要約して"),
            FixedPromptSlot(),
            FixedPromptSlot(),
        ],
        dropdown=[
            DropdownPrompt(id="d1", title="翻訳", body="英語に翻訳"),
        ],
    )
    save_prompts(tmp_path, saved)
    loaded = load_prompts(tmp_path)
    assert loaded.fixed[0].title == "要約"
    assert loaded.fixed[0].body == "3行で要約して"
    assert loaded.dropdown == [DropdownPrompt(id="d1", title="翻訳", body="英語に翻訳")]


def test_save_does_not_clobber_other_sections(tmp_path: Path):
    (tmp_path / "settings.json").write_text(
        '{"audio": {"whisper_model": "tiny"}}', encoding="utf-8"
    )
    save_prompts(tmp_path, PromptsSettings())
    import json as _json
    raw = _json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
    assert raw["audio"]["whisper_model"] == "tiny"
    assert "prompts" in raw


# --- 固定スロット CRUD ---------------------------------------------------


def test_set_fixed_overwrites_only_target_slot(tmp_path: Path):
    set_fixed(tmp_path, 1, title="要約", body="3行で要約")
    p = load_prompts(tmp_path)
    assert p.fixed[0].title == ""
    assert p.fixed[1].title == "要約"
    assert p.fixed[2].title == ""


@pytest.mark.parametrize("bad_slot", [-1, 3, 10])
def test_set_fixed_rejects_out_of_range(tmp_path: Path, bad_slot: int):
    with pytest.raises(AppError) as ei:
        set_fixed(tmp_path, bad_slot, title="x", body="y")
    assert ei.value.code == ErrorCode.INPUT_INVALID


def test_clear_fixed_empties_slot(tmp_path: Path):
    set_fixed(tmp_path, 0, title="A", body="B")
    cleared = clear_fixed(tmp_path, 0)
    assert cleared.fixed[0].title == ""
    assert cleared.fixed[0].body == ""
    assert cleared.fixed[0].icon_filename is None


# --- プルダウン CRUD -----------------------------------------------------


def test_add_dropdown_generates_uuid_and_appends(tmp_path: Path):
    a = add_dropdown(tmp_path, title="A", body="aaa")
    b = add_dropdown(tmp_path, title="B", body="bbb")
    p = load_prompts(tmp_path)
    assert len(p.dropdown) == 2
    assert p.dropdown[0].id == a.id
    assert p.dropdown[1].id == b.id
    assert a.id != b.id
    # uuid v4 形式(36 chars / 8-4-4-4-12)
    assert len(a.id) == 36
    assert a.id.count("-") == 4


def test_update_dropdown_keeps_id_and_edits_title_body(tmp_path: Path):
    a = add_dropdown(tmp_path, title="A", body="aaa")
    updated = update_dropdown(tmp_path, a.id, title="A2", body="aaa2")
    assert updated.id == a.id
    assert updated.title == "A2"
    assert updated.body == "aaa2"


def test_update_dropdown_unknown_id_raises_not_found(tmp_path: Path):
    with pytest.raises(AppError) as ei:
        update_dropdown(tmp_path, "missing-id", title="x", body="y")
    assert ei.value.code == ErrorCode.STORAGE_NOT_FOUND


def test_delete_dropdown_removes_target(tmp_path: Path):
    a = add_dropdown(tmp_path, title="A", body="aaa")
    b = add_dropdown(tmp_path, title="B", body="bbb")
    delete_dropdown(tmp_path, a.id)
    p = load_prompts(tmp_path)
    assert len(p.dropdown) == 1
    assert p.dropdown[0].id == b.id


def test_dropdown_capped_at_100(tmp_path: Path):
    for i in range(100):
        add_dropdown(tmp_path, title=f"t{i}", body="x")
    with pytest.raises(AppError) as ei:
        add_dropdown(tmp_path, title="t100", body="x")
    assert ei.value.code == ErrorCode.INPUT_INVALID


# --- 並び替え ------------------------------------------------------------


def test_reorder_dropdown_with_complete_ids_succeeds(tmp_path: Path):
    a = add_dropdown(tmp_path, title="A", body="x")
    b = add_dropdown(tmp_path, title="B", body="x")
    c = add_dropdown(tmp_path, title="C", body="x")
    reorder_dropdown(tmp_path, [c.id, a.id, b.id])
    p = load_prompts(tmp_path)
    assert [d.id for d in p.dropdown] == [c.id, a.id, b.id]


def test_reorder_dropdown_with_missing_id_raises(tmp_path: Path):
    a = add_dropdown(tmp_path, title="A", body="x")
    _b = add_dropdown(tmp_path, title="B", body="x")
    with pytest.raises(AppError) as ei:
        reorder_dropdown(tmp_path, [a.id])
    assert ei.value.code == ErrorCode.INPUT_INVALID


def test_reorder_dropdown_with_extra_id_raises(tmp_path: Path):
    a = add_dropdown(tmp_path, title="A", body="x")
    with pytest.raises(AppError) as ei:
        reorder_dropdown(tmp_path, [a.id, "ghost"])
    assert ei.value.code == ErrorCode.INPUT_INVALID


def test_reorder_dropdown_with_duplicate_id_raises(tmp_path: Path):
    a = add_dropdown(tmp_path, title="A", body="x")
    _b = add_dropdown(tmp_path, title="B", body="x")
    with pytest.raises(AppError) as ei:
        reorder_dropdown(tmp_path, [a.id, a.id])
    assert ei.value.code == ErrorCode.INPUT_INVALID


# --- 文字数バリデーション ----------------------------------------------


def test_set_fixed_rejects_title_over_100_chars(tmp_path: Path):
    with pytest.raises(AppError) as ei:
        set_fixed(tmp_path, 0, title="x" * 101, body="b")
    assert ei.value.code == ErrorCode.INPUT_INVALID


def test_set_fixed_rejects_body_over_10000_chars(tmp_path: Path):
    with pytest.raises(AppError) as ei:
        set_fixed(tmp_path, 0, title="t", body="x" * 10_001)
    assert ei.value.code == ErrorCode.INPUT_INVALID


def test_add_dropdown_rejects_title_over_100_chars(tmp_path: Path):
    with pytest.raises(AppError):
        add_dropdown(tmp_path, title="x" * 101, body="b")


def test_add_dropdown_rejects_body_over_10000_chars(tmp_path: Path):
    with pytest.raises(AppError):
        add_dropdown(tmp_path, title="t", body="x" * 10_001)
