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
        )

    @server.tool()
    async def find_quotes(notebook_id: str, query: str, max_quotes: int = 5) -> dict[str, Any]:
        return await find_quotes_tool(
            notebook_id=notebook_id,
            query=query,
            max_quotes=max_quotes,
            retrieval=ctx.retrieval,
            config=ctx.config,
        )

    @server.tool()
    def get_source_outline(source_id: str) -> dict[str, Any]:
        return get_source_outline_tool(conn=ctx.conn, source_id=source_id)

    return server


def build_mcp_asgi_app(ctx: Any):
    """Return the FastMCP SSE ASGI app for mounting."""
    server = build_mcp_server(ctx)
    return server.sse_app()
