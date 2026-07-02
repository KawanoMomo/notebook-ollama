"""未送信クラッシュレポート HTTP ルータ.

spec §7.1 / plan Sprint 3 Task 3.5.

Endpoints:
- ``GET    /api/crash/pending``                — 未送信レポート一覧
- ``POST   /api/crash/report``                 — フロントエンド由来クラッシュ即時登録
- ``POST   /api/crash/{crash_id}/dismiss``     — レポート却下 (削除)
- ``GET    /api/crash/{crash_id}/prefill-url`` — GitHub Issue 起票 prefill URL 生成
- ``POST   /api/crash/{crash_id}/mark-reported`` — 「GitHub で開く」押下時の確定

設計メモ:
- pending_store / reported_store / formatter / prefill_url は純粋関数の
  集合として既に Sprint 1〜2 で確定済み。本ルータは「FastAPI で外部に
  口を開ける」だけのアダプタ層。ロジックは下位モジュールへ委譲し、
  ここでは入力検証 / ステータスコード / dedup 経路の振り分けに集中する。
- ``POST /report`` は **フロント** から呼ばれる (Python 例外を経由しない
  経路) ため、collector.collect_from_exception は使わない。代わりに
  message + stack から ``PendingCrash`` を直接組み立てる。fingerprint
  は spec §9 (重複 Issue 抑制) を満たすため決定論的 SHA1 で計算する。
- dedup:
  1. ``reported_store.is_reported(fp)`` → 既に Issue 起票済。新規 pending
     は作らず、組み立て済 ``PendingCrash`` を 200 で返す (ユーザに「同じ
     バグはもう登録済みです」と暗黙に伝える)。
  2. pending に同 fingerprint が既存 → 既存 ``PendingCrash`` を 200 で
     返す (ID / created_at が変わらないので FE 側のキャッシュも整合)。
  3. それ以外 → 新規保存し 201 で返す。
- ``mark-reported`` は spec の「mark first, then delete」順序を守る。
  途中で delete が失敗してもユーザが同じバグで再 prompt されない方
  (= 安全側) に倒すための明示的な順序。
"""
from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from core.crash_reporter import pending_store, reported_store
from core.crash_reporter.formatter import (
    build_issue_body,
    build_issue_title,
    default_labels,
)
from core.crash_reporter.pending_store import PendingCrash
from core.crash_reporter.prefill_url import build_issue_url
from core.crash_reporter.redactor import redact_traceback

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/crash", tags=["crash"])


# ---------------------------------------------------------------------------
# Pydantic schemas (router-local: 単一ルータ専用のため schemas/ には出さない)
# ---------------------------------------------------------------------------


class CrashReportIn(BaseModel):
    """フロントエンド由来クラッシュの登録ペイロード.

    上限値の根拠:
    - ``message``  : 4_000 文字 — ブラウザの ``window.onerror`` が渡す
      message は通常 1〜2 行。万一スタックトレースを文字列連結された
      ケースに備えて余裕を持つ。
    - ``stack``    : 20_000 文字 — Chrome / Firefox の longest stack は
      数 KB 程度。SourceMap 展開済の Svelte stack も収まる範囲。
    - ``hardware`` : フロントから来る場合は ``navigator.userAgent`` / GPU
      情報など小さい dict。整形は formatter 側に任せる。
    """

    message: str = Field(min_length=1, max_length=4_000)
    stack: str | None = Field(default=None, max_length=20_000)
    hardware: dict | None = None
    # 現状フロントしか呼ばないが、将来 (CLI ツール等) からも叩けるよう
    # source は受け取る。pending_store.Source の Literal と一致しない
    # 値は 422 で弾く。
    source: str = Field(
        default="frontend",
        pattern=r"^(frontend|fastapi|excepthook|signal|atexit|unclean_shutdown)$",
    )


class PendingCrashOut(BaseModel):
    """``PendingCrash`` dataclass の HTTP 表現."""

    id: str
    fingerprint: str
    created_at: str
    exception_type: str
    exception_message: str
    trace: list[str]
    hardware: dict
    log_tail: list[dict]
    source: str


class PrefillUrlOut(BaseModel):
    url: str
    truncated: bool


class MarkReportedOut(BaseModel):
    ok: bool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _to_out(c: PendingCrash) -> PendingCrashOut:
    """``PendingCrash`` → ``PendingCrashOut`` (asdict 経由で安全コピー)."""
    d = asdict(c)
    return PendingCrashOut(**d)


def _now_iso_utc() -> str:
    """UTC ISO-8601 ``YYYY-MM-DDTHH:MM:SSZ`` (pending_store の created_at 形式)."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _frontend_fingerprint(message: str, stack_lines: list[str]) -> str:
    """フロントエンドクラッシュ用の決定論的 fingerprint.

    spec §9: 同一バグは同一 fingerprint。入力依存で揺れないよう、
    - 行番号 / カラム番号は捨てる (周辺コードの編集で fingerprint が
      変わると「同じバグ」を再報告してしまう)。
    - メッセージは 1 行目だけ採用 (Python ``compute_fingerprint`` が
      メッセージ本文を捨てるのと近い思想だが、フロントは型情報が
      薄いため最小限の判別シグナルとして 1 行目だけ残す)。
    - スタックは先頭 5 フレームまで使う (深さで揺れないため)。

    SHA1 は非暗号目的の dedup hash として使用 (重複 Issue 抑制のみ)。
    """
    msg_first_line = message.splitlines()[0] if message else ""
    parts: list[str] = ["frontend", msg_first_line]
    for line in stack_lines[:5]:
        # JS stack は "at funcName (file.js:42:10)" や "funcName@file.js:42:10"
        # 等の形式。行番号 / カラム番号を含む末尾 ":\d+:\d+" を雑に削ぐ。
        # `:` で split して先頭 2 つだけ (例: "at funcName (file.js" まで) を
        # 取る — 行番号より前で安定したシグナルになる。
        cleaned = ":".join(line.split(":")[:2]).strip()
        parts.append(cleaned)
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()  # noqa: S324


def _build_frontend_crash(
    *,
    message: str,
    stack: str | None,
    hardware: dict | None,
    source: str,
    app_root: Path,
) -> PendingCrash:
    """フロントエンドペイロード → ``PendingCrash`` (純粋関数; I/O なし).

    ``redact_traceback`` で HOME パス置換のみ行う (JS stack には Python の
    ``File "..."`` 行は無いが、Windows のフルパスが含まれる開発時のケース
    に備えて HOME を ``<HOME>`` に置換する念のための防御層)。
    """
    stack_lines = (stack or "").splitlines()
    redacted = redact_traceback(stack_lines, app_root)
    fp = _frontend_fingerprint(message, redacted)
    return PendingCrash(
        id=uuid.uuid4().hex,
        fingerprint=fp,
        created_at=_now_iso_utc(),
        exception_type="FrontendError",
        exception_message=message,
        trace=redacted,
        hardware=dict(hardware or {}),
        log_tail=[],
        source=source,  # type: ignore[arg-type]  # validated by Pydantic pattern
    )


def _find_pending_by_fingerprint(
    data_dir: Path, fingerprint: str
) -> PendingCrash | None:
    """同 fingerprint の pending crash を 1 件返す (dedup)."""
    for c in pending_store.load_all(data_dir):
        if c.fingerprint == fingerprint:
            return c
    return None


# ---------------------------------------------------------------------------
# endpoints
# ---------------------------------------------------------------------------


@router.get("/pending", response_model=list[PendingCrashOut])
async def list_pending(request: Request) -> list[PendingCrashOut]:
    """``crash-pending/*.json`` 全件を ``created_at`` 降順で返す."""
    data_dir: Path = request.app.state.ctx.config.data_dir
    return [_to_out(c) for c in pending_store.load_all(data_dir)]


@router.post(
    "/report",
    response_model=PendingCrashOut,
    responses={
        200: {
            "model": PendingCrashOut,
            "description": "同 fingerprint が既に pending or reported に存在 (dedup)",
        },
        201: {
            "model": PendingCrashOut,
            "description": "新規 pending として保存",
        },
    },
)
async def report_crash(
    payload: CrashReportIn, request: Request, response: Response
) -> PendingCrashOut:
    """フロント例外を pending に登録する.

    - reported_store に既に同 fingerprint あり → no-save, 200 (組み立て済
      crash を返す。FE は「もう登録済み」を判定するために fingerprint を
      参照できる)。
    - pending に同 fingerprint あり → 既存 ``PendingCrash`` を 200 で返す。
    - それ以外 → atomic write で保存し 201 で返す。
    """
    ctx = request.app.state.ctx
    # オプトイン未決定 / 明示拒否時は受け付けない (spec §5.9 / §7.3)。
    # 403 + detail="crash.opt_in_required" を返し、FE が「オプトインダイアログを
    # 表示すべき」と判断できるシグナルとして扱う。
    if ctx.config.crash_report.enabled is not True:
        raise HTTPException(
            status_code=403,
            detail="crash.opt_in_required",
        )
    data_dir: Path = ctx.config.data_dir
    # app_root: redact_traceback が「ここ配下の行は debug 用に保持」を判定
    # するためのヒント。CWD = 実行プロジェクトのルートで足りる。
    app_root = Path.cwd()

    crash = _build_frontend_crash(
        message=payload.message,
        stack=payload.stack,
        hardware=payload.hardware,
        source=payload.source,
        app_root=app_root,
    )

    # 既に Issue 化済 → no-save, 200
    if reported_store.is_reported(data_dir, crash.fingerprint):
        response.status_code = status.HTTP_200_OK
        return _to_out(crash)

    # 既に pending にある → 既存を返す (新規保存しない)
    existing = _find_pending_by_fingerprint(data_dir, crash.fingerprint)
    if existing is not None:
        response.status_code = status.HTTP_200_OK
        return _to_out(existing)

    pending_store.save(data_dir, crash)
    response.status_code = status.HTTP_201_CREATED
    return _to_out(crash)


@router.post("/{crash_id}/dismiss", status_code=204)
async def dismiss_crash(crash_id: str, request: Request) -> Response:
    """pending を削除する (ユーザ却下)."""
    data_dir: Path = request.app.state.ctx.config.data_dir
    deleted = pending_store.delete(data_dir, crash_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"crash {crash_id} not found")
    return Response(status_code=204)


@router.get("/{crash_id}/prefill-url", response_model=PrefillUrlOut)
async def get_prefill_url(crash_id: str, request: Request) -> PrefillUrlOut:
    """GitHub Issue 起票 prefill URL (title + body + labels) を返す.

    URL が 8KB に収まらなければ formatter / prefill_url 内部のロジックで
    log_tail を段階的に切り詰める (``truncated=True`` で通知)。
    """
    data_dir: Path = request.app.state.ctx.config.data_dir
    crash = pending_store.get(data_dir, crash_id)
    if crash is None:
        raise HTTPException(status_code=404, detail=f"crash {crash_id} not found")
    crash_dict = asdict(crash)
    title = build_issue_title(crash_dict)
    body = build_issue_body(crash_dict)
    labels = default_labels(crash_dict)
    url, truncated = build_issue_url(title=title, body=body, labels=labels)
    return PrefillUrlOut(url=url, truncated=truncated)


@router.post("/{crash_id}/mark-reported", response_model=MarkReportedOut)
async def mark_crash_reported(crash_id: str, request: Request) -> MarkReportedOut:
    """「GitHub で開く」押下時に呼ばれる. pending → reported に移送する.

    順序は **mark first, then delete**:
    - mark が成功 → delete が失敗してもユーザが再 prompt されない (spec §9)。
    - 逆順 (delete → mark) だと delete 成功 + mark 失敗で fingerprint が
      消失し、同じバグで再びユーザに promptされる事故が起こる。
    """
    data_dir: Path = request.app.state.ctx.config.data_dir
    crash = pending_store.get(data_dir, crash_id)
    if crash is None:
        raise HTTPException(status_code=404, detail=f"crash {crash_id} not found")
    reported_store.mark_reported(data_dir, crash.fingerprint)
    pending_store.delete(data_dir, crash_id)
    return MarkReportedOut(ok=True)
