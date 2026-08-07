import pytest

from core.retrieval.span_scorer import SpanCache, is_cross_language, score_spans


class FakeGateway:
    """文ごとに決め打ちのベクトルを返すスタブ。呼び出し回数も数える。"""

    def __init__(self, vectors: dict[str, list[float]]):
        self.vectors = vectors
        self.calls = 0

    async def embed(self, *, model: str, text: str) -> list[float]:
        self.calls += 1
        for key, vec in self.vectors.items():
            if key in text:
                return vec
        return [0.0, 1.0]


CHUNK = "Level 1 indicates outcome achievement. Level 2 requires work product management."


@pytest.mark.asyncio
async def test_returns_span_for_most_similar_sentence():
    gw = FakeGateway({"レベル2": [1.0, 0.0], "Level 2": [0.98, 0.02], "Level 1": [0.0, 1.0]})
    got = await score_spans(
        claim="レベル2では作業成果物が管理される",
        chunk_text=CHUNK,
        chunk_id="c1",
        gateway=gw,
        model="bge-m3",
        cache=SpanCache(),
    )
    assert len(got) == 1
    assert "Level 2" in got[0]["quote"]
    assert got[0]["method"] == "embedding"
    assert got[0]["ordinal"] is None


@pytest.mark.asyncio
async def test_returns_empty_when_no_sentence_stands_out():
    gw = FakeGateway({"レベル2": [1.0, 0.0], "Level 2": [0.7, 0.7], "Level 1": [0.7, 0.7]})
    got = await score_spans(
        claim="レベル2では作業成果物が管理される",
        chunk_text=CHUNK,
        chunk_id="c1",
        gateway=gw,
        model="bge-m3",
        cache=SpanCache(),
    )
    assert got == []


@pytest.mark.asyncio
async def test_skips_when_model_is_not_multilingual_and_languages_differ():
    gw = FakeGateway({"レベル2": [1.0, 0.0], "Level 2": [0.98, 0.02]})
    got = await score_spans(
        claim="レベル2では作業成果物が管理される",
        chunk_text=CHUNK,
        chunk_id="c1",
        gateway=gw,
        model="nomic-embed-text",
        cache=SpanCache(),
    )
    assert got == []
    assert gw.calls == 0  # 埋め込みを1回も呼ばない


@pytest.mark.asyncio
async def test_cache_prevents_recomputation():
    gw = FakeGateway({"レベル2": [1.0, 0.0], "Level 2": [0.98, 0.02], "Level 1": [0.0, 1.0]})
    cache = SpanCache()
    kwargs = dict(
        claim="レベル2では作業成果物が管理される",
        chunk_text=CHUNK,
        chunk_id="c1",
        gateway=gw,
        model="bge-m3",
        cache=cache,
    )
    await score_spans(**kwargs)
    first = gw.calls
    await score_spans(**kwargs)
    assert gw.calls == first


def test_cache_evicts_beyond_limit():
    cache = SpanCache(limit=2)
    cache.put(("a", "1", "m"), [])
    cache.put(("b", "1", "m"), [])
    cache.put(("c", "1", "m"), [])
    assert cache.get(("a", "1", "m")) is None
    assert cache.get(("c", "1", "m")) is not None


def test_is_cross_language():
    assert is_cross_language("レベル2では管理される", "Level 2 requires management.")
    assert not is_cross_language("レベル2では管理される", "レベル2の要求事項")
