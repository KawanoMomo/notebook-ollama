from __future__ import annotations

import pytest

from core.eval.metrics import matches, mrr, recall_at_k


def test_matches_identical_strings():
    assert matches("送信 FIFO は 16 段", "送信 FIFO は 16 段") is True


def test_matches_near_identical_strings():
    assert matches("送信 FIFO は 16 段である", "送信 FIFO は 16 段") is True


def test_matches_rejects_unrelated_strings():
    assert matches("送信 FIFO は 16 段", "電源電圧は 3.3V") is False


def test_matches_respects_threshold():
    a, b = "abcdefgh", "abcdxxxx"
    assert matches(a, b, threshold=0.4) is True
    assert matches(a, b, threshold=0.9) is False


def test_recall_at_k_all_found():
    assert recall_at_k(["A の本文", "B の本文"], ["A の本文", "B の本文"]) == 1.0


def test_recall_at_k_none_found():
    assert recall_at_k(["まったく別の文章"], ["A の本文"]) == 0.0


def test_recall_at_k_partial():
    # 正解2件のうち1件だけ引けている状態。2つの正解は互いに十分異なる
    # 文字列でなければならない ("A の本文" / "B の本文" のような1文字違いは
    # 類似度 0.8 で閾値 0.6 を超え、同一チャンク扱いになってしまう)。
    score = recall_at_k(
        ["送信 FIFO は 16 段", "無関係な文章"],
        ["送信 FIFO は 16 段", "電源電圧は 3.3V"],
    )
    assert score == pytest.approx(0.5)


def test_recall_at_k_empty_retrieved_is_zero():
    assert recall_at_k([], ["A の本文"]) == 0.0


def test_recall_at_k_empty_reference_is_zero():
    assert recall_at_k(["A の本文"], []) == 0.0


def test_mrr_first_position():
    assert mrr(["A の本文", "無関係"], ["A の本文"]) == pytest.approx(1.0)


def test_mrr_third_position():
    retrieved = ["無関係な文章1", "無関係な文章2", "A の本文"]
    assert mrr(retrieved, ["A の本文"]) == pytest.approx(1 / 3)


def test_mrr_no_hit_is_zero():
    assert mrr(["無関係な文章"], ["A の本文"]) == 0.0


def test_mrr_uses_earliest_hit_among_multiple_references():
    retrieved = ["無関係な文章", "電源電圧は 3.3V", "送信 FIFO は 16 段"]
    reference = ["送信 FIFO は 16 段", "電源電圧は 3.3V"]
    assert mrr(retrieved, reference) == pytest.approx(0.5)


def test_mrr_empty_inputs_are_zero():
    assert mrr([], ["A の本文"]) == 0.0
    assert mrr(["A の本文"], []) == 0.0


from core.eval.metrics import QuestionScore, ragas_available, score_question


def test_score_question_without_ragas_fills_own_metrics():
    score = score_question(
        id="q001",
        kind="table",
        retrieved=["A の本文", "無関係"],
        reference=["A の本文"],
        use_ragas=False,
    )

    assert isinstance(score, QuestionScore)
    assert score.id == "q001"
    assert score.kind == "table"
    assert score.recall_at_k == pytest.approx(1.0)
    assert score.mrr == pytest.approx(1.0)


def test_score_question_without_ragas_leaves_ragas_metrics_none():
    score = score_question(
        id="q001",
        kind="text",
        retrieved=["A の本文"],
        reference=["A の本文"],
        use_ragas=False,
    )

    assert score.context_recall is None
    assert score.context_precision is None


def test_score_question_miss_scores_zero():
    score = score_question(
        id="q001",
        kind="figure",
        retrieved=["まったく別の文章"],
        reference=["A の本文"],
        use_ragas=False,
    )

    assert score.recall_at_k == 0.0
    assert score.mrr == 0.0


def test_ragas_available_returns_bool():
    assert isinstance(ragas_available(), bool)


@pytest.mark.skipif(not ragas_available(), reason="ragas 未導入 (eval extra)")
def test_score_question_with_ragas_scores_perfect_hit():
    """完全一致なら Ragas の両指標とも満点になる。

    値域だけを見る表明では「常に 0.0 を返す」「別のメトリクスに
    差し替わった」といった回帰を検出できないため、実測値で固定する。
    precision は内部の正規化で厳密な 1.0 にならないので近似比較にする。
    """
    score = score_question(
        id="q001",
        kind="table",
        retrieved=["送信 FIFO は 16 段"],
        reference=["送信 FIFO は 16 段"],
        use_ragas=True,
    )

    assert score.context_recall == pytest.approx(1.0)
    assert score.context_precision == pytest.approx(1.0, abs=1e-6)


@pytest.mark.skipif(not ragas_available(), reason="ragas 未導入 (eval extra)")
async def test_score_question_with_ragas_works_inside_running_event_loop():
    """async 文脈から呼んでも Ragas 指標が欠測にならない。

    CLI の `_render` は async な `_amain` の中から同期呼び出しされる。
    `asyncio.run()` を素で呼ぶと `RuntimeError: asyncio.run() cannot be called
    from a running event loop` になり、広域 except が握って両指標が None に
    なる = レポートの主指標2列が全条件 `—` のまま完走してしまう。
    同期文脈からしか呼ばないテストではこの欠陥を捕まえられない。
    """
    score = score_question(
        id="q001",
        kind="table",
        retrieved=["送信 FIFO は 16 段"],
        reference=["送信 FIFO は 16 段"],
        use_ragas=True,
    )

    assert score.context_recall is not None
    assert score.context_precision is not None
    assert score.context_recall == pytest.approx(1.0)


@pytest.mark.skipif(not ragas_available(), reason="ragas 未導入 (eval extra)")
def test_score_question_with_ragas_scores_empty_retrieval_as_zero():
    """1件も引けなかった条件は欠測ではなく 0 点。

    Ragas の NonLLM メトリクスは空の retrieved_contexts に対して
    `max() iterable argument is empty` で落ちるため、放置すると最も成績の
    悪い条件だけが主指標の平均から抜け、壊れた設定が良く見える方向に効く。
    自前指標 (recall_at_k / mrr) の空入力時の扱いとも揃える。
    """
    score = score_question(
        id="q001",
        kind="table",
        retrieved=[],
        reference=["送信 FIFO は 16 段"],
        use_ragas=True,
    )

    assert score.context_recall == 0.0
    assert score.context_precision == 0.0


@pytest.mark.skipif(not ragas_available(), reason="ragas 未導入 (eval extra)")
def test_score_question_with_ragas_scores_complete_miss():
    """完全不一致なら Ragas の両指標とも 0 になる。"""
    score = score_question(
        id="q001",
        kind="table",
        retrieved=["電源電圧は 3.3V"],
        reference=["送信 FIFO は 16 段"],
        use_ragas=True,
    )

    assert score.context_recall == pytest.approx(0.0)
    assert score.context_precision == pytest.approx(0.0)
