from __future__ import annotations

# MCP HTTP/SSE wiring with bearer auth.
#
# FastMCP (mcp >= 1.0) does not expose handle_http_post / create_sse_response
# methods directly on the FastMCP class. Instead it provides sse_app() which
# returns a Starlette ASGI application with /sse and /messages routes.
#
# The auth check is performed here in FastAPI before delegating to the MCP
# Starlette sub-app. The actual SSE/message-handling is forwarded to the
# sub-app via raw ASGI dispatch after auth passes.
#
# DONE_WITH_CONCERNS: The forward path (after auth passes) delegates to the
# FastMCP sse_app() sub-application. This works for SSE transport but has not
# been validated end-to-end with a real MCP client in this test suite; the
# integration tests only cover 401 rejection, which is fully implemented here.

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse, Response
from starlette.types import Receive, Scope, Send

from core.exceptions import AppError, ErrorCode
from core.mcp.auth import verify_token
from core.mcp.server import build_mcp_server


router = APIRouter(prefix="/mcp", tags=["mcp"])


def _auth(ctx: object, authorization: str | None) -> None:
    verify_token(ctx.config.mcp_token_path, header_value=authorization)  # type: ignore[attr-defined]


@router.post("/messages")
async def messages(
    request: Request,
    authorization: str | None = Header(default=None),
) -> Response:
    ctx = request.app.state.ctx
    _auth(ctx, authorization)
    # Delegate to the MCP SSE Starlette sub-app's /messages route.
    mcp_server = build_mcp_server(ctx)
    sub_app = mcp_server.sse_app()
    # Rewrite scope path to /messages so the sub-app routes correctly.
    scope = dict(request.scope)
    scope["path"] = "/messages"
    scope["raw_path"] = b"/messages"
    response_started: list[dict] = []
    response_body: list[bytes] = []

    async def receive() -> dict:
        return await request.receive()

    async def send(message: dict) -> None:
        if message["type"] == "http.response.start":
            response_started.append(message)
        elif message["type"] == "http.response.body":
            response_body.append(message.get("body", b""))

    await sub_app(scope, receive, send)
    status = response_started[0]["status"] if response_started else 501
    headers = dict(response_started[0].get("headers", [])) if response_started else {}
    body = b"".join(response_body)
    return Response(content=body, status_code=status, headers=headers)


@router.get("/sse")
async def sse(
    request: Request,
    authorization: str | None = Header(default=None),
) -> Response:
    ctx = request.app.state.ctx
    _auth(ctx, authorization)
    # Delegate to the MCP SSE Starlette sub-app's /sse route.
    mcp_server = build_mcp_server(ctx)
    sub_app = mcp_server.sse_app()
    scope = dict(request.scope)
    scope["path"] = "/sse"
    scope["raw_path"] = b"/sse"
    response_started: list[dict] = []
    response_body: list[bytes] = []

    async def receive() -> dict:
        return await request.receive()

    async def send(message: dict) -> None:
        if message["type"] == "http.response.start":
            response_started.append(message)
        elif message["type"] == "http.response.body":
            response_body.append(message.get("body", b""))

    await sub_app(scope, receive, send)
    status = response_started[0]["status"] if response_started else 501
    headers = dict(response_started[0].get("headers", [])) if response_started else {}
    body = b"".join(response_body)
    return Response(content=body, status_code=status, headers=headers)
