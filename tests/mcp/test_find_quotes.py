import pytest

from core.mcp.tools.find_quotes import find_quotes_tool
from core.retrieval.search import RetrievedChunk


class FakeRetrieval:
    async def search(self, *, notebook_id, query, limit):
        return [
            RetrievedChunk(
                chunk_id=f"c{i}",
                source_id=f"s{i}",
                source_title=f"Doc{i}",
                source_kind="md",
                page=i,
                heading_path=None,
                ord=i,
                text=f"quote body {i}",
                token_count=3,
                score=0.5,
            )
            for i in range(7)
        ]


@pytest.mark.asyncio
async def test_find_quotes_respects_max_and_returns_no_generation():
    from types import SimpleNamespace

    out = await find_quotes_tool(
        notebook_id="nb",
        query="anything",
        max_quotes=3,
        retrieval=FakeRetrieval(),
        config=SimpleNamespace(visual=SimpleNamespace(search_strategy="hybrid_rrf")),
    )
    assert len(out["quotes"]) == 3
    q = out["quotes"][0]
    assert q["text"] == "quote body 0"
    assert q["source_title"] == "Doc0"
    assert q["location"] == "p.0"


@pytest.mark.asyncio
async def test_find_quotes_rejects_pixel_native_strategy():
    """最終レビュー I1: find_quotes も ask と同じ理由で pixel_native を拒否する
    (MCP 経路には画像投入機構が無く、プレースホルダ本文だけが返る)。"""
    from types import SimpleNamespace

    from core.exceptions import AppError

    with pytest.raises(AppError):
        await find_quotes_tool(
            notebook_id="nb",
            query="anything",
            max_quotes=3,
            retrieval=FakeRetrieval(),
            config=SimpleNamespace(visual=SimpleNamespace(search_strategy="pixel_native")),
        )
