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
