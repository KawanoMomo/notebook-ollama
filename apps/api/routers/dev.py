"""開発者モード API(spec: docs/specs/2026-07-02-developer-mode-design.md §9)。

全エンドポイントの先頭で guard_dev_request を評価する(I11):
設定 ON かつ client IP が localhost の AND。X-Forwarded-For は読まない(NFR-3)。
"""
from __future__ import annotations

import asyncio
import json
import subprocess
from typing import Any, Literal

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from sse_starlette.sse import EventSourceResponse

from core.dev_logs.broker import broker
from core.dev_logs.ring import ring
from core.exceptions import AppError, ErrorCode

router = APIRouter(prefix="/api/dev", tags=["dev"])

_LOCALHOSTS = ("127.0.0.1", "::1")


def guard_dev_request(request: Request) -> None:
    """設定 ON かつ localhost のときだけ通す。それ以外は一律 403(§5.2)。"""
    ctx = request.app.state.ctx
    if not ctx.config.dev.enabled:
        raise AppError(ErrorCode.DEV_UNAUTHORIZED, "developer mode is disabled")
    host = request.client.host if request.client else None
    if host not in _LOCALHOSTS:
        raise AppError(ErrorCode.DEV_UNAUTHORIZED, "developer mode is disabled")


@router.get("/stream")
async def dev_stream(request: Request, since_seq: int | None = None):
    guard_dev_request(request)

    async def gen():
        sub = broker.subscribe()
        try:
            # §7.5: since_seq が oldest より古ければ gap を 1 件先行通知
            oldest = ring.oldest_seq
            start_after = since_seq
            if since_seq is not None and since_seq + 1 < oldest:
                yield {"event": "gap", "data": json.dumps({"lost_until": oldest})}
                start_after = oldest - 1
            # 追いつき(snapshot)。購読登録後に読むことで取りこぼしを防ぎ、
            # 重複は seq で FE 側もデデュープできるよう last_seq を進める
            last_seq = 0
            res = ring.read(after_seq=start_after, limit=100000)
            for e in res.entries:
                last_seq = e["seq"]
                yield {"event": "entry", "data": json.dumps(e, ensure_ascii=False)}
            while True:
                if await request.is_disconnected():
                    return
                try:
                    ev = await asyncio.wait_for(sub.queue.get(), timeout=15)
                except TimeoutError:
                    yield {"event": "ping", "data": ""}
                    continue
                if ev.get("event") == "shutdown":
                    yield {"event": "shutdown", "data": "{}"}
                    return
                if ev.get("event") == "entry":
                    data = ev.get("data", {})
                    if data.get("seq", 0) <= last_seq:
                        continue  # snapshot と重複
                    last_seq = data.get("seq", last_seq)
                    yield {
                        "event": "entry",
                        "data": json.dumps(data, ensure_ascii=False),
                    }
                else:
                    yield {
                        "event": ev.get("event", "meta"),
                        "data": json.dumps(ev.get("data", {}), ensure_ascii=False),
                    }
        finally:
            broker.unsubscribe(sub)

    return EventSourceResponse(gen())


@router.get("/range")
async def dev_range(
    request: Request,
    after_seq: int | None = None,
    before_seq: int | None = None,
    limit: int = 500,
    order: Literal["asc", "desc"] = "asc",
) -> dict[str, Any]:
    guard_dev_request(request)
    res = ring.read(
        after_seq=after_seq,
        before_seq=before_seq,
        limit=max(1, min(limit, 5000)),
        order=order,
    )
    return {
        "entries": res.entries,
        "first_seq": res.first_seq,
        "last_seq": res.last_seq,
        "gap_before": res.gap_before,
        "gap_after": res.gap_after,
        "oldest_seq": res.oldest_seq,
        "latest_seq": res.latest_seq,
    }


@router.get("/stats")
async def dev_stats(request: Request) -> dict[str, Any]:
    guard_dev_request(request)
    return dict(ring.stats)


@router.post("/clear")
async def dev_clear(request: Request) -> dict[str, Any]:
    guard_dev_request(request)
    ring.clear()
    return dict(ring.stats)


@router.get("/system")
async def dev_system(request: Request) -> dict[str, Any]:
    guard_dev_request(request)
    ctx = request.app.state.ctx
    models: list[str] = []
    try:
        tags = await ctx.ollama_gateway._client.list_tags()  # noqa: SLF001 — 診断用途
        models = [t.get("name", "") for t in tags]
    except Exception:  # noqa: S110 — Ollama 停止中でも system 情報は返す
        pass
    git_rev = ""
    try:
        git_rev = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5, check=False,
        ).stdout.strip()
    except Exception:  # noqa: S110
        pass
    cfg = ctx.config
    snapshot = {
        "default_model": cfg.ollama.default_model,
        "embedding_model": cfg.ollama.embedding_model,
        "generation": cfg.generation.model_dump(),
        "dev": cfg.dev.model_dump(),
    }
    return {"ollama_models": models, "git_rev": git_rev, "config_snapshot": snapshot}


@router.get("/export.ndjson")
async def dev_export(
    request: Request,
    after_seq: int | None = None,
    before_seq: int | None = None,
):
    guard_dev_request(request)
    res = ring.read(after_seq=after_seq, before_seq=before_seq, limit=10**9)

    def _iter():
        for e in res.entries:
            yield json.dumps(e, ensure_ascii=False) + "\n"

    return StreamingResponse(
        _iter(),
        media_type="application/x-ndjson",
        headers={"Content-Disposition": "attachment; filename=dev-logs.ndjson"},
    )
