"""第2段の堅牢化(検証で見つかった4件)の回帰テスト。

いずれも「無言で品質が落ちる」類の欠陥で、既存テストでは検出できていなかった。
"""

from __future__ import annotations

import pytest

from core.retrieval.span_scorer import SpanCache, score_spans, split_sentences


class FakeGateway:
    def __init__(self, vectors: dict[str, list[float]]):
        self.vectors = vectors
        self.calls = 0

    async def embed(self, *, model: str, text: str) -> list[float]:
        self.calls += 1
        for key, vec in self.vectors.items():
            if key in text:
                return vec
        return [0.0, 1.0]


def test_abbreviation_followed_by_capital_is_not_a_boundary():
    """`e.g. Sleep` の直後が大文字でも略語なら文境界にしない。"""
    text = "The device supports several modes, e.g. Sleep and Deep Sleep. Refer to the table."
    got = split_sentences(text)
    assert len(got) == 2
    assert "e.g. Sleep and Deep Sleep." in got[0].text


@pytest.mark.parametrize("abbrev", ["Fig.", "No.", "i.e.", "cf.", "vs.", "Eq.", "Sec."])
def test_common_abbreviations_do_not_split(abbrev: str):
    text = f"See {abbrev} Alpha for the detail of this behaviour. Then continue reading here."
    got = split_sentences(text)
    assert len(got) == 2, f"{abbrev} で過分割した: {[s.text for s in got]}"


def test_real_sentence_boundary_still_splits():
    text = "The process achieves its outcomes. The next requirement follows here."
    got = split_sentences(text)
    assert len(got) == 2


def test_offsets_still_map_to_original():
    text = "See Fig. Alpha for details of the mode. Then the next sentence follows."
    for s in split_sentences(text):
        assert text[s.start : s.end] == s.text


@pytest.mark.asyncio
async def test_empty_claim_does_not_call_embedding():
    gw = FakeGateway({})
    got = await score_spans(
        claim="   ",
        chunk_text="First sentence here. Second sentence here.",
        chunk_id="c1",
        gateway=gw,
        model="bge-m3",
        cache=SpanCache(),
    )
    assert got == []
    assert gw.calls == 0


@pytest.mark.asyncio
async def test_span_has_no_leading_or_trailing_whitespace():
    chunk = "Level 1 indicates outcome achievement.\n Level 2 requires work product management. "
    gw = FakeGateway({"レベル2": [1.0, 0.0], "Level 2": [0.99, 0.01], "Level 1": [0.0, 1.0]})
    got = await score_spans(
        claim="レベル2では作業成果物が管理される",
        chunk_text=chunk,
        chunk_id="c1",
        gateway=gw,
        model="bge-m3",
        cache=SpanCache(),
    )
    assert len(got) == 1
    span = got[0]
    assert span["quote"] == span["quote"].strip()
    # start/end もトリム後の位置を指すこと(FE のハイライト位置がずれないため)
    assert chunk[span["start"] : span["end"]] == span["quote"]


@pytest.mark.asyncio
async def test_cache_returns_a_copy_not_the_stored_list():
    gw = FakeGateway({"レベル2": [1.0, 0.0], "Level 2": [0.99, 0.01], "Level 1": [0.0, 1.0]})
    cache = SpanCache()
    kwargs = dict(
        claim="レベル2では作業成果物が管理される",
        chunk_text="Level 1 indicates outcome achievement. Level 2 requires work product management.",
        chunk_id="c1",
        gateway=gw,
        model="bge-m3",
        cache=cache,
    )
    first = await score_spans(**kwargs)
    first.append({"injected": True})  # 呼び出し側が壊しても
    second = await score_spans(**kwargs)
    assert second == [s for s in second if "injected" not in s]
    assert len(second) == 1
