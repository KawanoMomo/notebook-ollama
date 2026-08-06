from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from core.eval.metrics import QuestionScore
from core.eval.report import ConditionSummary, render_report, summarize


def _score(id_, kind, recall, mrr_):
    return QuestionScore(
        id=id_,
        kind=kind,
        recall_at_k=recall,
        mrr=mrr_,
        context_recall=recall,
        context_precision=recall,
    )


def test_summarize_averages_overall_metrics():
    summary = summarize(
        condition_id="abc",
        overrides={"top_k": 8},
        scores=[_score("q1", "text", 1.0, 1.0), _score("q2", "text", 0.0, 0.0)],
        elapsed_s=1.5,
    )

    assert summary.overall["recall_at_k"] == pytest.approx(0.5)
    assert summary.overall["mrr"] == pytest.approx(0.5)
    assert summary.elapsed_s == 1.5


def test_summarize_splits_by_kind():
    summary = summarize(
        condition_id="abc",
        overrides={},
        scores=[
            _score("q1", "table", 1.0, 1.0),
            _score("q2", "figure", 0.0, 0.0),
            _score("q3", "table", 0.0, 0.0),
        ],
        elapsed_s=0.0,
    )

    assert summary.by_kind["table"]["recall_at_k"] == pytest.approx(0.5)
    assert summary.by_kind["figure"]["recall_at_k"] == pytest.approx(0.0)
    assert "text" not in summary.by_kind


def test_summarize_ignores_none_ragas_metrics():
    scores = [
        QuestionScore(id="q1", kind="text", recall_at_k=1.0, mrr=1.0),
        QuestionScore(id="q2", kind="text", recall_at_k=0.0, mrr=0.0),
    ]

    summary = summarize(
        condition_id="abc", overrides={}, scores=scores, elapsed_s=0.0
    )

    assert "context_recall" not in summary.overall
    assert summary.overall["recall_at_k"] == pytest.approx(0.5)


def test_summarize_failed_condition_has_empty_metrics():
    summary = summarize(
        condition_id="abc",
        overrides={"search_strategy": "pixel_native"},
        scores=[],
        elapsed_s=0.2,
        failed_reason="pixel_native は視覚索引が未構築のため使用不可",
    )

    assert summary.overall == {}
    assert summary.failed_reason is not None


def test_render_report_marks_baseline_row():
    base = summarize(
        condition_id="base01",
        overrides={"top_k": 8},
        scores=[_score("q1", "text", 1.0, 1.0)],
        elapsed_s=1.0,
    )

    md = render_report([base], sweep_name="s", baseline_id="base01")

    assert "base01" in md
    assert "baseline" in md


def test_render_report_shows_delta_from_baseline():
    base = summarize(
        condition_id="base01",
        overrides={"top_k": 8},
        scores=[_score("q1", "text", 0.5, 0.5)],
        elapsed_s=1.0,
    )
    other = summarize(
        condition_id="othr01",
        overrides={"top_k": 12},
        scores=[_score("q1", "text", 1.0, 1.0)],
        elapsed_s=1.0,
    )

    md = render_report([base, other], sweep_name="s", baseline_id="base01")

    assert "+0.500" in md


def test_render_report_lists_failed_conditions_with_reason():
    failed = summarize(
        condition_id="fail01",
        overrides={"search_strategy": "pixel_native"},
        scores=[],
        elapsed_s=0.1,
        failed_reason="視覚索引が未構築",
    )

    md = render_report([failed], sweep_name="s", baseline_id="fail01")

    assert "視覚索引が未構築" in md
    assert "失敗" in md


def test_render_report_includes_kind_breakdown_section():
    s = summarize(
        condition_id="base01",
        overrides={},
        scores=[_score("q1", "table", 1.0, 1.0), _score("q2", "figure", 0.0, 0.0)],
        elapsed_s=0.0,
    )

    md = render_report([s], sweep_name="s", baseline_id="base01")

    assert "kind 別" in md
    assert "table" in md
    assert "figure" in md


def test_render_report_handles_empty_summaries():
    md = render_report([], sweep_name="s", baseline_id="x")

    assert "s" in md


def test_condition_summary_is_frozen():
    s = ConditionSummary(
        condition_id="x",
        overrides={},
        overall={},
        by_kind={},
        elapsed_s=0.0,
        failed_reason=None,
    )
    with pytest.raises(FrozenInstanceError):
        s.condition_id = "y"  # type: ignore[misc]
