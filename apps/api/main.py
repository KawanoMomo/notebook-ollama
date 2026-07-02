from __future__ import annotations

# Use the OS-native trust store (Windows cert store, macOS Keychain,
# Linux openssl path) instead of the certifi bundle. Required for sites
# whose certificate chain is rooted at CAs not present in certifi
# (e.g. autosar.org). Must run before any SSLContext is created.
import truststore

truststore.inject_into_ssl()

import logging  # noqa: E402
from contextlib import asynccontextmanager  # noqa: E402

from fastapi import FastAPI  # noqa: E402
from fastapi.requests import Request  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from starlette.responses import JSONResponse as StarletteJSONResponse  # noqa: E402
from starlette.types import Receive, Scope, Send  # noqa: E402

from apps.api.dependencies import build_context  # noqa: E402
from apps.api.routers import (  # noqa: E402
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
from apps.api.routers import (  # noqa: E402
    models as models_router,
)
from apps.api.routers import (  # noqa: E402
    settings as settings_router,
)
from core.config import AppConfig  # noqa: E402
from core.crash_reporter import collector as crash_collector  # noqa: E402
from core.crash_reporter import lifecycle as crash_lifecycle  # noqa: E402
from core.exceptions import AppError  # noqa: E402
from core.logging import configure_logging  # noqa: E402

logger = logging.getLogger(__name__)


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
    """FastAPI lifespan with crash-report lifecycle wiring.

    Sprint 4 Task 4.3. The crash auto-detection pipeline (file-backed
    JSON-lines log sink, ``running.lock`` ownership, log-tail recovery
    of unclean prior shutdowns, in-process trap collector) is **only**
    activated when ``config.crash_report.enabled is True`` (spec §5.9 —
    explicit opt-in required). With ``enabled`` set to ``None`` (not yet
    decided) or ``False`` (explicit opt-out), the lifespan skips ALL of
    log capture / lock / collector registration — the Feedback Hub still
    works through the manual ``/api/crash/report`` and
    ``/api/feedback-hub/*`` routers, but no background auto-collection
    runs and nothing is written under ``data_dir`` for crash
    bookkeeping.

    On the happy path (enabled=True), the order is intentional:

    1. ``configure_logging(logs_dir=...)`` rotates the previous session's
       ``last-session.log`` → ``last-session.log.prev`` and installs the
       redacted JSON-lines file sink so subsequent logs land in the new
       ``last-session.log`` (Sprint 4 Task 4.1).
    2. ``lifecycle.acquire`` stamps our PID into ``running.lock``. If
       the prior PID is dead, it returns an :class:`UncleanShutdown`;
       we then run ``collect_pending_from_log_tail`` to convert the
       rotated log into a ``PendingCrash`` JSON file (dedup against
       ``reported.txt`` is enforced inside that helper).
    3. ``crash_collector.register`` installs the live traps (FastAPI
       exception handler, ``sys.excepthook``, signal handlers, atexit).

    Shutdown order is the reverse and runs in a ``finally`` so a
    ``yield`` that raises does not leak handlers or strand the lock:

    1. ``crash_collector.unregister`` (only if we actually registered).
    2. ``lifecycle.release(running_lock_path)`` (only if we actually
       acquired). Idempotent on a missing file — defensive against
       ``release`` racing with manual deletion.
    3. App context teardown (vector store + sqlite conn) — preserved
       from the prior lifespan, but defensively guarded so a partial
       startup does not raise during teardown.
    """
    config = AppConfig()
    from core.settings_store import apply_overrides
    apply_overrides(config)

    crash_enabled = config.crash_report.enabled is True
    # Track which lifecycle steps actually succeeded so the finally
    # block does not call ``release`` / ``unregister`` for steps that
    # never ran (avoiding spurious log noise + AttributeError chains).
    locked = False
    registered = False

    try:
        if crash_enabled:
            # 1. Rotate the previous session log + open the redacted
            #    JSON-lines file sink. ``rotate_last_session`` is invoked
            #    inside ``configure_logging(logs_dir=...)`` and is a
            #    no-op if no prior ``last-session.log`` exists.
            configure_logging(logs_dir=config.logs_dir)

            # 2. Stamp the lock with our PID and recover any unclean
            #    prior session. ``acquire`` always writes our PID into
            #    the lock (whether or not the prior was unclean) and
            #    returns ``UncleanShutdown`` only when the prior PID
            #    can be proven dead.
            unclean = crash_lifecycle.acquire(config.running_lock_path)
            locked = True
            if unclean is not None:
                # collect_pending_from_log_tail enforces opt-in + dedup
                # internally. We still wrap to make absolutely certain
                # that a forensics failure cannot abort startup.
                try:
                    crash_lifecycle.collect_pending_from_log_tail(
                        unclean.prev_log_path,
                        config.data_dir,
                        config.crash_report,
                    )
                except Exception:
                    logger.exception(
                        "lifespan: collect_pending_from_log_tail failed"
                    )

            # 3. Install all crash traps. Pending and reported stores
            #    both interpret their path arg as a *data dir* (they
            #    derive ``crash-pending/`` and ``reported.txt`` from it
            #    internally), so we pass the data_dir for both.
            crash_collector.register(
                app,
                settings=config.crash_report,
                pending_store_dir=config.data_dir,
                reported_store_path=config.data_dir,
            )
            registered = True
        else:
            # Auto-detection is dormant; keep the stderr-only structlog
            # config the rest of the codebase expects.
            configure_logging()

        app.state.ctx = build_context(config)
        from apps.api import _mcp_state
        _mcp_state.ctx = app.state.ctx
        yield
    finally:
        # Each shutdown step is independently guarded so one failure
        # cannot prevent the others from running.
        if registered:
            try:
                crash_collector.unregister()
            except Exception:
                logger.exception("lifespan: crash_collector.unregister failed")
        if locked:
            try:
                crash_lifecycle.release(config.running_lock_path)
            except Exception:
                logger.exception("lifespan: lifecycle.release failed")
        ctx = getattr(app.state, "ctx", None)
        if ctx is not None:
            try:
                ctx.vector_store.close()
            except Exception:
                logger.exception("lifespan: vector_store.close failed")
            try:
                ctx.conn.close()
            except Exception:
                logger.exception("lifespan: conn.close failed")


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
