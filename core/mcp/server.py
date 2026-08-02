from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from core.mcp.tools.ask import ask_tool
from core.mcp.tools.find_quotes import find_quotes_tool
from core.mcp.tools.get_source_outline import get_source_outline_tool
from core.mcp.tools.list_models import list_models_tool
from core.mcp.tools.list_notebooks import list_notebooks_tool
from core.ollama.client import OllamaClient
from core.storage import notebooks_repo


def _strategy(ctx: Any) -> str | None:
    """ベータOFF時に既定へ丸めた実効の検索戦略。

    `config.visual.search_strategy` は永続化されるため、`pixel_native` を選んだ後に
    ベータをOFFにすると値だけが残る。生値で判定すると、機能自体が無効なのに
    「MCP は pixel-native に対応していません」という**原因と違うエラー**になる。
    実効値は build_context が組み立てて AppContext に載せる (生成側と同じ値)。

    テスト等で `effective_visual_strategy` を持たない簡易 ctx の場合は None を返し、
    呼び出し先が `config.visual.search_strategy` にフォールバックする。
    """
    getter = getattr(ctx, "effective_visual_strategy", None)
    return getter() if callable(getter) else None


def build_mcp_server(ctx: Any) -> FastMCP:
    server = FastMCP("notebook-ollama")

    @server.tool()
    def list_notebooks() -> dict[str, Any]:
        return list_notebooks_tool(ctx.conn)

    @server.tool()
    async def list_models() -> dict[str, Any]:
        client = OllamaClient(
            endpoint=ctx.config.ollama.endpoint,
            timeout=ctx.config.ollama.request_timeout_seconds,
        )
        return await list_models_tool(conn=ctx.conn, client=client)

    @server.tool()
    async def ask(
        notebook_id: str,
        question: str,
        model: str | None = None,
        style: str = "concise",
    ) -> dict[str, Any]:
        nb = notebooks_repo.get_notebook(ctx.conn, notebook_id)
        client = OllamaClient(
            endpoint=ctx.config.ollama.endpoint,
            timeout=ctx.config.ollama.request_timeout_seconds,
        )
        return await ask_tool(
            notebook_id=notebook_id,
            question=question,
            model=model,
            style=style,
            retrieval=ctx.retrieval,
            ollama=ctx.ollama,
            client=client,
            config=ctx.config,
            notebook_default_model=nb.default_model,
            search_strategy=_strategy(ctx),
        )

    @server.tool()
    async def find_quotes(notebook_id: str, query: str, max_quotes: int = 5) -> dict[str, Any]:
        return await find_quotes_tool(
            notebook_id=notebook_id,
            query=query,
            max_quotes=max_quotes,
            retrieval=ctx.retrieval,
            config=ctx.config,
            search_strategy=_strategy(ctx),
        )

    @server.tool()
    def get_source_outline(source_id: str) -> dict[str, Any]:
        return get_source_outline_tool(conn=ctx.conn, source_id=source_id)

    return server


def build_mcp_asgi_app(ctx: Any):
    """Return the FastMCP SSE ASGI app for mounting."""
    server = build_mcp_server(ctx)
    return server.sse_app()
