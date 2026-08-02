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


class _LocationRetrieval:
    def __init__(self, **overrides):
        self._overrides = overrides

    async def search(self, *, notebook_id, query, limit):
        base = dict(
            chunk_id="c1", source_id="s1", source_title="T", source_kind="pdf",
            page=None, heading_path=None, ord=0, text="x", token_count=1, score=0.9,
        )
        base.update(self._overrides)
        return [RetrievedChunk(**base)]


async def _quote_location(retrieval) -> str:
    from types import SimpleNamespace

    out = await find_quotes_tool(
        notebook_id="nb", query="q", max_quotes=1, retrieval=retrieval,
        config=SimpleNamespace(visual=SimpleNamespace(search_strategy="hybrid_rrf")),
    )
    return out["quotes"][0]["location"]


@pytest.mark.asyncio
async def test_find_quotes_location_keeps_speaker_and_timecode():
    """回帰テスト: 録音チャンクで location が空文字になっていた (ask と同一原因)。"""
    loc = await _quote_location(
        _LocationRetrieval(source_kind="recording", start_ms=65000, speaker="話者A")
    )
    assert loc == "話者A 00:01:05"


@pytest.mark.asyncio
async def test_find_quotes_location_keeps_tile_index():
    """回帰テスト: タイル索引の「タイルN」表記が落ちていた。"""
    assert await _quote_location(_LocationRetrieval(page=12, tile_index=1)) == "p.12 タイル2"


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


@pytest.mark.asyncio
async def test_find_quotes_beta_off_does_not_reject_stale_pixel_native():
    """回帰テスト: ベータOFFで pixel_native の設定値だけが残っている場合、
    「MCP は pixel-native に対応していません」という原因と違うエラーになっていた。

    実効戦略 (build_context の _effective_strategy) はベータOFF時に hybrid_rrf へ
    丸めるので、その値が渡ればテキスト検索として通る。
    """
    from types import SimpleNamespace

    out = await find_quotes_tool(
        notebook_id="nb", query="q", max_quotes=1, retrieval=FakeRetrieval(),
        config=SimpleNamespace(visual=SimpleNamespace(search_strategy="pixel_native")),
        search_strategy="hybrid_rrf",   # ベータOFFで丸められた実効値
    )
    assert out["quotes"][0]["location"] == "p.0"


@pytest.mark.asyncio
async def test_find_quotes_still_rejects_pixel_native_when_beta_on():
    """ベータONで実際に pixel_native なら従来どおり拒否すること。"""
    from types import SimpleNamespace

    from core.exceptions import AppError

    with pytest.raises(AppError):
        await find_quotes_tool(
            notebook_id="nb", query="q", max_quotes=1, retrieval=FakeRetrieval(),
            config=SimpleNamespace(visual=SimpleNamespace(search_strategy="pixel_native")),
            search_strategy="pixel_native",
        )
