from __future__ import annotations

import pytest
from dataclasses import FrozenInstanceError

from core.eval.matrix import (
    Condition,
    MatrixError,
    SweepSpec,
    condition_id,
    expand,
    load_sweep,
    partition,
    reindex_count,
)

BASELINE = {"tile_rows": 3, "search_strategy": "hybrid_rrf", "top_k": 8}


def _spec(axes):
    return SweepSpec(
        name="s",
        corpus="data/eval/corpus/sample.pdf",
        golden="data/eval/golden.jsonl",
        notebook_id="eval-notebook",
        baseline=dict(BASELINE),
        axes=axes,
    )


def test_condition_id_is_stable_across_key_order():
    assert condition_id({"a": 1, "b": 2}) == condition_id({"b": 2, "a": 1})


def test_condition_id_differs_for_different_values():
    assert condition_id({"a": 1}) != condition_id({"a": 2})


def test_condition_id_is_short_hex():
    cid = condition_id({"a": 1})
    assert len(cid) == 12
    assert all(c in "0123456789abcdef" for c in cid)


def test_expand_produces_cartesian_product():
    conditions = expand(_spec({"top_k": [5, 8], "search_strategy": ["hybrid_rrf", "visual_only"]}))

    combos = {(c.overrides["top_k"], c.overrides["search_strategy"]) for c in conditions}
    assert combos == {
        (5, "hybrid_rrf"),
        (5, "visual_only"),
        (8, "hybrid_rrf"),
        (8, "visual_only"),
    }


def test_expand_fills_unswept_keys_from_baseline():
    conditions = expand(_spec({"top_k": [5, 8]}))

    assert conditions[0].overrides["tile_rows"] == 3
    assert conditions[0].overrides["search_strategy"] == "hybrid_rrf"


def test_expand_puts_baseline_condition_first():
    conditions = expand(_spec({"top_k": [5, 8, 12]}))

    assert conditions[0].overrides["top_k"] == 8
    assert conditions[0].id == condition_id(BASELINE)


def test_expand_with_no_axes_yields_baseline_only():
    conditions = expand(_spec({}))

    assert len(conditions) == 1
    assert conditions[0].overrides == BASELINE


def test_expand_rejects_axis_absent_from_baseline():
    with pytest.raises(MatrixError, match="baseline"):
        expand(_spec({"unknown_key": [1, 2]}))


def test_expand_rejects_empty_axis():
    with pytest.raises(MatrixError, match="空"):
        expand(_spec({"top_k": []}))


def test_expand_rejects_axis_whose_values_omit_the_baseline_value():
    # baseline が条件に含まれないと report の差分列が丸ごと消える (静かな誤読)。
    with pytest.raises(MatrixError, match="top_k"):
        expand(_spec({"top_k": [5, 12]}))


def test_expand_rejects_baseline_without_top_k():
    spec = SweepSpec(
        name="s",
        corpus="c",
        golden="g",
        notebook_id="n",
        baseline={"search_strategy": "hybrid_rrf"},
        axes={},
    )
    with pytest.raises(MatrixError, match="top_k"):
        expand(spec)


def test_load_sweep_rejects_baseline_without_top_k(tmp_path):
    path = tmp_path / "matrix.yaml"
    path.write_text(
        "name: s\n"
        "corpus: c\n"
        "golden: g\n"
        "notebook_id: n\n"
        "baseline: {search_strategy: hybrid_rrf}\n",
        encoding="utf-8",
    )

    with pytest.raises(MatrixError, match="top_k"):
        load_sweep(path)


def test_search_time_axes_do_not_require_reindex():
    conditions = expand(
        _spec({"top_k": [5, 8], "search_strategy": ["hybrid_rrf", "visual_only"]})
    )

    assert all(not c.requires_reindex for c in conditions)


def test_tile_rows_axis_requires_reindex_for_non_baseline():
    conditions = expand(_spec({"tile_rows": [1, 3, 5]}))
    by_rows = {c.overrides["tile_rows"]: c for c in conditions}

    assert by_rows[3].requires_reindex is False  # baseline と同じ索引を使える
    assert by_rows[1].requires_reindex is True
    assert by_rows[5].requires_reindex is True


def test_partition_splits_by_reindex_flag():
    conditions = expand(_spec({"tile_rows": [1, 3], "top_k": [5, 8]}))

    search_only, reindex = partition(conditions)

    assert all(not c.requires_reindex for c in search_only)
    assert all(c.requires_reindex for c in reindex)
    assert len(search_only) + len(reindex) == len(conditions)


def test_reindex_count_counts_distinct_index_shapes():
    conditions = expand(_spec({"tile_rows": [1, 3, 5], "top_k": [5, 8]}))

    # tile_rows 3値 × top_k 2値 = 6条件だが、索引構築は tile_rows ごとに
    # 1回で足りる。baseline (3) は既存索引を使うので追加構築は 2 回。
    assert reindex_count(conditions) == 2


def test_load_sweep_reads_yaml(tmp_path):
    path = tmp_path / "matrix.yaml"
    path.write_text(
        "name: tile-and-strategy\n"
        "corpus: data/eval/corpus/sample.pdf\n"
        "golden: data/eval/golden.jsonl\n"
        "notebook_id: eval-notebook\n"
        "baseline: {tile_rows: 3, search_strategy: hybrid_rrf, top_k: 8}\n"
        "axes:\n"
        "  tile_rows: [1, 3, 5]\n"
        "  top_k: [5, 8, 12]\n",
        encoding="utf-8",
    )

    spec = load_sweep(path)

    assert spec.name == "tile-and-strategy"
    assert spec.notebook_id == "eval-notebook"
    assert spec.baseline["top_k"] == 8
    assert spec.axes["tile_rows"] == [1, 3, 5]


def test_load_sweep_rejects_missing_required_key(tmp_path):
    path = tmp_path / "matrix.yaml"
    path.write_text("name: s\naxes: {}\n", encoding="utf-8")

    with pytest.raises(MatrixError, match="corpus"):
        load_sweep(path)


def test_condition_is_frozen():
    c = Condition(id="x", overrides={}, requires_reindex=False)
    with pytest.raises(FrozenInstanceError):
        c.id = "y"  # type: ignore[misc]
