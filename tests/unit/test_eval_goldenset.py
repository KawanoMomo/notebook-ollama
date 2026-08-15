from __future__ import annotations

import json

import pytest

from core.eval.goldenset import (
    GoldenItem,
    GoldenSetError,
    dump_golden,
    load_golden,
)


def _write(tmp_path, rows):
    path = tmp_path / "golden.jsonl"
    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
        encoding="utf-8",
    )
    return path


def test_load_golden_reads_all_fields(tmp_path):
    path = _write(
        tmp_path,
        [
            {
                "id": "q001",
                "question": "SPI の送信 FIFO 深さは何段か",
                "reference_contexts": ["送信 FIFO は 16 段"],
                "page_no": 412,
                "kind": "table",
            }
        ],
    )

    items = load_golden(path)

    assert len(items) == 1
    assert items[0] == GoldenItem(
        id="q001",
        question="SPI の送信 FIFO 深さは何段か",
        reference_contexts=["送信 FIFO は 16 段"],
        page_no=412,
        kind="table",
    )


def test_load_golden_allows_missing_page_no(tmp_path):
    path = _write(
        tmp_path,
        [
            {
                "id": "q001",
                "question": "概要は",
                "reference_contexts": ["本文"],
                "kind": "text",
            }
        ],
    )

    assert load_golden(path)[0].page_no is None


def test_load_golden_skips_blank_lines(tmp_path):
    path = tmp_path / "golden.jsonl"
    path.write_text(
        '{"id":"q001","question":"q","reference_contexts":["c"],"kind":"text"}\n'
        "\n"
        '{"id":"q002","question":"q","reference_contexts":["c"],"kind":"text"}\n',
        encoding="utf-8",
    )

    assert len(load_golden(path)) == 2


def test_load_golden_rejects_unknown_kind(tmp_path):
    path = _write(
        tmp_path,
        [
            {
                "id": "q001",
                "question": "q",
                "reference_contexts": ["c"],
                "kind": "diagram",
            }
        ],
    )

    with pytest.raises(GoldenSetError, match="kind"):
        load_golden(path)


def test_load_golden_rejects_empty_reference_contexts(tmp_path):
    path = _write(
        tmp_path,
        [{"id": "q001", "question": "q", "reference_contexts": [], "kind": "text"}],
    )

    with pytest.raises(GoldenSetError, match="reference_contexts"):
        load_golden(path)


def test_load_golden_rejects_duplicate_ids(tmp_path):
    row = {"id": "q001", "question": "q", "reference_contexts": ["c"], "kind": "text"}
    path = _write(tmp_path, [row, dict(row)])

    with pytest.raises(GoldenSetError, match="重複"):
        load_golden(path)


def test_dump_then_load_roundtrips(tmp_path):
    items = [
        GoldenItem(
            id="q001",
            question="表の値は",
            reference_contexts=["16 段", "32 バイト"],
            page_no=7,
            kind="table",
        ),
        GoldenItem(
            id="q002",
            question="図の意味は",
            reference_contexts=["ブロック図"],
            page_no=None,
            kind="figure",
        ),
    ]
    path = tmp_path / "out.jsonl"

    dump_golden(items, path)

    assert load_golden(path) == items
