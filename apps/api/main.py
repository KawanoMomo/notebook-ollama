from __future__ import annotations

# Use the OS-native trust store (Windows cert store, macOS Keychain,
# Linux openssl path) instead of the certifi bundle. Required for sites
# whose certificate chain is rooted at CAs not present in certifi
# (e.g. autosar.org). Must run before any SSLContext is created.
import truststore

truststore.inject_into_ssl()

import json  # noqa: E402
from contextlib import asynccontextmanager  # noqa: E402

from fastapi import FastAPI
from fastapi.requests import Request
from fastapi.responses import JSONResponse
from starlette.responses import JSONResponse as StarletteJSONResponse
from starlette.types import Receive, Scope, Send

from apps.api.dependencies import build_context
from apps.api.routers import (
    audio,
    chat,
    crash,
    events,
    feedback_hub,
    health,
    notebooks,
    prompts,
    recording_ws,
    recordings,
    sources,
)
from apps.api.routers import (
    models as models_router,
)
from apps.api.routers import (
    settings as settings_router,
)
from core.config import AppConfig
from core.exceptions import AppError
from core.logging import configure_logging


class _McpAsgiProxy:
    """Lazy proxy that builds the mcp sse_app from _mcp_state.ctx on first call.

    Performs bearer-token auth before forwarding to the inner SSE app.
    Mounted ASGI apps see their own scope and cannot reliably access the parent
    FastAPI app's state, so we use a module-level reference populated during
    lifespan instead.
    """

    def __init__(self) -> None:
        self._app = None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            return

        # Retrieve auth header
        headers = dict(scope.get("headers") or [])
        auth = headers.get(b"authorization", b"").decode("latin-1")

        # Obtain ctx from module-level state (set in lifespan)
        from apps.api import _mcp_state  # type: ignore
        ctx = _mcp_state.ctx

        try:
            from core.mcp.auth import verify_token
            verify_token(ctx.config.mcp_token_path, header_value=auth or None)
        except AppError as exc:
            resp = StarletteJSONResponse(status_code=401, content=exc.to_dict())
            await resp(scope, receive, send)
            return
        except Exception:
            resp = StarletteJSONResponse(
                status_code=401,
                content={"error": {"code": "mcp.unauthorized", "message": "unauthorized"}},
            )
            await resp(scope, receive, send)
            return

        # Auth passed — build (or reuse) the inner SSE app and forward
        if self._app is None:
            from core.mcp.server import build_mcp_asgi_app
            self._app = build_mcp_asgi_app(ctx)
        await self._app(scope, receive, send)


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    config = AppConfig()
    from core.settings_store import apply_overrides
    apply_overrides(config)
    app.state.ctx = build_context(config)
    from apps.api import _mcp_state
    _mcp_state.ctx = app.state.ctx
    yield
    app.state.ctx.vector_store.close()
    app.state.ctx.conn.close()


def create_app(config: AppConfig | None = None) -> FastAPI:
    app = FastAPI(title="Notebook Ollama", lifespan=lifespan)

    @app.exception_handler(AppError)
    async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
        status_map = {
            "input.invalid": 400,
            "input.payload_too_large": 413,
            "input.unsupported_media": 415,
            "ingestion.unsupported_kind": 400,
            "ingestion.duplicate": 409,
            "storage.not_found": 404,
            "storage.conflict": 409,
            "ollama.unreachable": 503,
            "ollama.model_not_found": 404,
            "mcp.unauthorized": 401,
        }
        return JSONResponse(
            status_code=status_map.get(exc.code.value, 500),
            content=exc.to_dict(),
        )

    app.include_router(health.router)
    app.include_router(notebooks.router)
    app.include_router(sources.router)
    app.include_router(recordings.router)
    app.include_router(recording_ws.router)
    app.include_router(audio.router)
    app.include_router(chat.router)
    app.include_router(models_router.router)
    app.include_router(settings_router.router)
    app.include_router(prompts.router)
    app.include_router(events.router)
    app.include_router(feedback_hub.router)
    app.include_router(crash.router)
    app.mount("/mcp", _McpAsgiProxy())

    from pathlib import Path
    from starlette.responses import FileResponse
    web_dist = Path(__file__).parents[1] / "web" / "dist"
    if web_dist.is_dir():
        # SPA フォールバック: SvelteKit の動的ルート(/notebooks/{id}, /settings 等)
        # は dist にファイルが無い。StaticFiles(html=True) は SPA fallback を
        # 実装しないため、catch-all で「存在ファイル→そのまま、存在しない→
        # index.html」を提供する。これがないと:
        #   1. /notebooks/{id} へ直アクセス・F5 リロードが 404
        #   2. ハイドレーション前のクリックがネイティブ遷移して 404
        # 加えて index.html には no-cache を付け、再ビルドで _app/immutable の
        # ハッシュが変わったときに古い HTML が居座って 404 を出すのを防ぐ。
        _index_html = web_dist / "index.html"
        _web_dist_resolved = web_dist.resolve()
        _no_cache_headers = {"Cache-Control": "no-cache, must-revalidate"}

        from fastapi import HTTPException
        from starlette.responses import Response

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa_or_static(full_path: str) -> Response:
            # `/api/...` と `/mcp/...` は専用ルーター/マウントが扱う範囲。
            # ここまで来た = 専用ルートで match しなかった = 本物の 404。
            # SPA fallback で index.html を返すと API クライアントが HTML を
            # 受け取って混乱するため、明示的に 404 を返す。
            if full_path.startswith("api/") or full_path.startswith("mcp"):
                raise HTTPException(status_code=404, detail="Not Found")
            # path traversal の defense-in-depth: 解決後に web_dist 配下に
            # 収まらないパスは候補から外し、index.html へフォールバック。
            try:
                candidate = (web_dist / full_path).resolve()
                candidate.relative_to(_web_dist_resolved)
                inside = True
            except (ValueError, OSError):
                inside = False
            if inside and candidate.is_file():
                # 静的アセット(ハッシュ付き immutable / favicon 等)はキャッシュ
                # 可能のまま配信する(starlette の既定 Cache-Control に任せる)。
                return FileResponse(candidate)
            return FileResponse(_index_html, headers=_no_cache_headers)

    return app


app = create_app()
