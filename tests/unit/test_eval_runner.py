from __future__ import annotations

import json

import pytest

from core.eval.goldenset import GoldenItem
from core.eval.matrix import Condition
from core.eval.runner import (
    ConditionFailed,
    completed_condition_ids,
    run_sweep,
)

GOLDEN = [
    GoldenItem(id="q1", question="Q1", reference_contexts=["A の本文"], kind="text"),
    GoldenItem(id="q2", question="Q2", reference_contexts=["B の本文"], kind="table"),
]


def _cond(cid, **overrides):
    return Condition(id=cid, overrides=overrides, requires_reindex=False)


def _read(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _fake_clock():
    """呼ばれるたびに 1.0 ずつ進む単調時計。"""
    state = {"t": 0.0}

    def now() -> float:
        state["t"] += 1.0
        return state["t"]

    return now


@pytest.mark.asyncio
async def test_run_sweep_writes_one_row_per_question(tmp_path):
    path = tmp_path / "results.jsonl"

    async def search(*, condition, item):
        return [item.reference_contexts[0]]

    await run_sweep(
        conditions=[_cond("c1", top_k=8)],
        golden=GOLDEN,
        search=search,
        results_path=path,
        now=_fake_clock(),
    )

    rows = _read(path)
    question_rows = [r for r in rows if r["type"] == "question"]
    assert len(question_rows) == 2
    assert {r["question_id"] for r in question_rows} == {"q1", "q2"}
    assert question_rows[0]["retrieved_contexts"] == ["A の本文"]


@pytest.mark.asyncio
async def test_run_sweep_writes_condition_marker_with_elapsed(tmp_path):
    path = tmp_path / "results.jsonl"

    async def search(*, condition, item):
        return []

    await run_sweep(
        conditions=[_cond("c1", top_k=8)],
        golden=GOLDEN,
        search=search,
        results_path=path,
        now=_fake_clock(),
    )

    markers = [r for r in _read(path) if r["type"] == "condition"]
    assert len(markers) == 1
    assert markers[0]["condition_id"] == "c1"
    assert markers[0]["failed_reason"] is None
    assert markers[0]["elapsed_s"] > 0


@pytest.mark.asyncio
async def test_run_sweep_records_failure_and_continues(tmp_path):
    path = tmp_path / "results.jsonl"

    async def search(*, condition, item):
        if condition.id == "bad":
            raise ConditionFailed("視覚索引が未構築")
        return ["A の本文"]

    await run_sweep(
        conditions=[_cond("bad"), _cond("good")],
        golden=GOLDEN,
        search=search,
        results_path=path,
        now=_fake_clock(),
    )

    markers = {r["condition_id"]: r for r in _read(path) if r["type"] == "condition"}
    assert markers["bad"]["failed_reason"] == "視覚索引が未構築"
    assert markers["good"]["failed_reason"] is None


@pytest.mark.asyncio
async def test_run_sweep_treats_unexpected_exception_as_condition_failure(tmp_path):
    path = tmp_path / "results.jsonl"

    async def search(*, condition, item):
        if condition.id == "boom":
            raise RuntimeError("CUDA out of memory")
        return ["A の本文"]

    await run_sweep(
        conditions=[_cond("boom"), _cond("ok")],
        golden=GOLDEN,
        search=search,
        results_path=path,
        now=_fake_clock(),
    )

    markers = {r["condition_id"]: r for r in _read(path) if r["type"] == "condition"}
    assert "CUDA out of memory" in markers["boom"]["failed_reason"]
    assert markers["ok"]["failed_reason"] is None


@pytest.mark.asyncio
async def test_completed_condition_ids_reads_markers(tmp_path):
    path = tmp_path / "results.jsonl"

    async def search(*, condition, item):
        return ["A の本文"]

    await run_sweep(
        conditions=[_cond("c1"), _cond("c2")],
        golden=GOLDEN,
        search=search,
        results_path=path,
        now=_fake_clock(),
    )

    assert completed_condition_ids(path) == {"c1", "c2"}


def test_completed_condition_ids_on_missing_file_is_empty(tmp_path):
    assert completed_condition_ids(tmp_path / "nope.jsonl") == set()


@pytest.mark.asyncio
async def test_run_sweep_skips_already_completed_conditions(tmp_path):
    path = tmp_path / "results.jsonl"
    calls: list[str] = []

    async def search(*, condition, item):
        calls.append(condition.id)
        return ["A の本文"]

    await run_sweep(
        conditions=[_cond("c1")],
        golden=GOLDEN,
        search=search,
        results_path=path,
        now=_fake_clock(),
    )
    calls.clear()

    await run_sweep(
        conditions=[_cond("c1"), _cond("c2")],
        golden=GOLDEN,
        search=search,
        results_path=path,
        now=_fake_clock(),
    )

    assert set(calls) == {"c2"}


@pytest.mark.asyncio
async def test_run_sweep_failed_condition_counts_as_completed(tmp_path):
    """失敗も記録済みなので、再開時に無限リトライしない。"""
    path = tmp_path / "results.jsonl"

    async def search(*, condition, item):
        raise ConditionFailed("だめ")

    await run_sweep(
        conditions=[_cond("c1")],
        golden=GOLDEN,
        search=search,
        results_path=path,
        now=_fake_clock(),
    )

    assert completed_condition_ids(path) == {"c1"}
