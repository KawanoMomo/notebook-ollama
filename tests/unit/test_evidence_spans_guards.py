"""第1段の防御的な上限と、合成チャンクの除外。

背景:
- `_best_window` が窓ごとにスライスと set を作り直しており O(ペア数 * 窓内ペア数)
  だった。反復の多いチャンク(空白も句読点も無い日本語 = PDF の表の抽出結果)で
  秒〜分単位に膨れ、かつ生成ストリームの中で同期に走るためイベントループ全体が
  止まっていた。
- 視覚検索の pixel-native チャンクは本文ではなくプロンプト用のプレースホルダを
  text に持つ。そこにスパンが乗ると、システム自身の指示文を「根拠」として
  無関係な位置に描画してしまう。
"""

from __future__ import annotations

import random
import time

from core.generation.evidence_spans import (
    MAX_CHUNK_CHARS,
    NGRAM,
    _best_window,
    attach_evidence_spans,
    resolve_lexical_span,
)

CHUNK = (
    "プロセス能力レベル1は、実施されたプロセスの成果が達成されていることを示す。"
    "レベル2では作業成果物が適切に管理される。"
)


def _best_window_reference(pairs, claim_len):
    """線形化する前の素朴な実装(等価性の基準)。"""
    if not pairs:
        return []
    width = max(claim_len * 2, NGRAM * 4)
    ordered = sorted(pairs, key=lambda p: p[1])
    best: list[tuple[int, int]] = []
    left = 0
    for right in range(len(ordered)):
        while ordered[right][1] - ordered[left][1] > width:
            left += 1
        window = ordered[left : right + 1]
        if len({p[0] for p in window}) > len({p[0] for p in best}):
            best = window
    return best


def test_best_window_matches_reference_implementation():
    rng = random.Random(20260807)
    for _ in range(200):
        pairs = [(rng.randrange(0, 30), rng.randrange(0, 400)) for _ in range(rng.randrange(0, 60))]
        claim_len = rng.randrange(6, 60)
        assert _best_window(pairs, claim_len) == _best_window_reference(pairs, claim_len)


def test_pathological_repetition_returns_none_quickly():
    """同一文字が延々と続くチャンク。以前は数十秒〜数分かかっていた。"""
    chunk = "あ" * 40_000
    claim = "あ" * 100
    started = time.perf_counter()
    assert resolve_lexical_span(claim, chunk) is None
    assert time.perf_counter() - started < 2.0


def test_chunk_over_limit_is_skipped_rather_than_scanned():
    """上限超えのチャンクは逐語一致があっても諦める(偽陰性側に倒す)。"""
    filler = "測定項目値判定基準備考該当なし要確認"
    chunk = filler * ((MAX_CHUNK_CHARS // len(filler)) + 10)
    assert len(chunk) > MAX_CHUNK_CHARS
    assert resolve_lexical_span("レベル2では作業成果物が適切に管理される", chunk + CHUNK) is None


def test_large_but_bounded_chunk_stays_fast():
    """上限直下のチャンクでも、引用1件あたりの照合が実用時間に収まる。"""
    filler = "測定項目値判定基準備考該当なし要確認"
    chunk = (filler * (MAX_CHUNK_CHARS // len(filler)))[: MAX_CHUNK_CHARS - len(CHUNK)] + CHUNK
    started = time.perf_counter()
    span = resolve_lexical_span("レベル2では作業成果物が適切に管理される", chunk)
    elapsed = time.perf_counter() - started
    assert span is not None
    assert elapsed < 1.0


def test_pixel_native_placeholder_gets_no_spans():
    """合成チャンク(vp: / vt:)のプレースホルダ本文には根拠を付けない。"""
    placeholder = (
        "(このソースはページ画像として添付されています。"
        "添付画像を読み取って回答の根拠にしてください)"
    )
    answer = "このソースはページ画像として添付されています[^1]。"
    got = attach_evidence_spans(
        answer=answer,
        citations=[{"n": 1, "chunk_id": "vp:s1:12"}],
        chunk_texts={"vp:s1:12": placeholder},
    )
    assert got[0]["spans"] == []


def test_pixel_native_tile_placeholder_gets_no_spans():
    placeholder = (
        "(このソースはページ画像の一部(タイル)として添付されています。"
        "添付画像を読み取って回答の根拠にしてください)"
    )
    answer = "添付画像を読み取って回答の根拠にしてください[^2]。"
    got = attach_evidence_spans(
        answer=answer,
        citations=[{"n": 2, "chunk_id": "vt:s1:12:3"}],
        chunk_texts={"vt:s1:12:3": placeholder},
    )
    assert got[0]["spans"] == []


def test_real_chunk_alongside_synthetic_still_resolves():
    """合成チャンクの除外が普通のチャンクを巻き込まないこと。"""
    answer = (
        "このソースはページ画像として添付されています[^1]。"
        "レベル2では作業成果物が適切に管理される[^2]。"
    )
    got = attach_evidence_spans(
        answer=answer,
        citations=[{"n": 1, "chunk_id": "vp:s1:12"}, {"n": 2, "chunk_id": "c1"}],
        chunk_texts={"vp:s1:12": "このソースはページ画像として添付されています", "c1": CHUNK},
    )
    assert got[0]["spans"] == []
    assert len(got[1]["spans"]) == 1
    assert got[1]["spans"][0]["answer_occurrence"] == 1
