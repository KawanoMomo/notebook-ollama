from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from core.exceptions import AppError, ErrorCode
from core.ids import new_id


class SourceStatus(StrEnum):
    PENDING = "pending"
    PARSING = "parsing"
    CHUNKING = "chunking"
    EMBEDDING = "embedding"
    READY = "ready"
    ERROR = "error"


class SummaryStatus(StrEnum):
    GENERATING = "generating"
    READY = "ready"
    ERROR = "error"


class AdrStatus(StrEnum):
    """ADR 抽出ジョブの状態。

    SKIPPED は Decision Gate で「ADR にすべき情報が無い」と判定された状態で、
    SummaryStatus には無い ADR 固有のステート。再試行は可能だが、ユーザに
    「議事録には Decision が無さそう」と説明する文言を出して reTry を促さない。
    """

    GENERATING = "generating"
    READY = "ready"
    ERROR = "error"
    SKIPPED = "skipped"


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class SourceRecord:
    id: str
    notebook_id: str
    kind: str
    title: str | None
    origin: str | None
    content_hash: str | None
    status: SourceStatus
    error_msg: str | None
    # AppError.remediation。message だけでは「何をすれば直るか」が伝わらない
    # ため、UI へ届けるために保持する(実機FB 2026-07-26)。
    error_remediation: str | None
    bytes: int | None
    page_count: int | None
    chunk_count: int | None
    summary: str | None
    summary_status: SummaryStatus | None
    adr_draft: str | None
    adr_status: AdrStatus | None
    adr_template: str | None
    adr_confidence: str | None
    adr_generated_at: str | None
    created_at: str
    updated_at: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> SourceRecord:
        keys = row.keys()
        summary = row["summary"] if "summary" in keys else None
        raw_status = row["summary_status"] if "summary_status" in keys else None
        adr_draft = row["adr_draft"] if "adr_draft" in keys else None
        adr_status_raw = row["adr_status"] if "adr_status" in keys else None
        adr_template = row["adr_template"] if "adr_template" in keys else None
        adr_confidence = row["adr_confidence"] if "adr_confidence" in keys else None
        adr_generated_at = (
            row["adr_generated_at"] if "adr_generated_at" in keys else None
        )
        return cls(
            id=row["id"],
            notebook_id=row["notebook_id"],
            kind=row["kind"],
            title=row["title"],
            origin=row["origin"],
            content_hash=row["content_hash"],
            status=SourceStatus(row["status"]),
            error_msg=row["error_msg"],
            # マイグレーション前の DB / 部分SELECT でも読めるようにする
            error_remediation=(
                row["error_remediation"] if "error_remediation" in keys else None
            ),
            bytes=row["bytes"],
            page_count=row["page_count"],
            chunk_count=row["chunk_count"],
            summary=summary,
            summary_status=SummaryStatus(raw_status) if raw_status else None,
            adr_draft=adr_draft,
            adr_status=AdrStatus(adr_status_raw) if adr_status_raw else None,
            adr_template=adr_template,
            adr_confidence=adr_confidence,
            adr_generated_at=adr_generated_at,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


def create_source(
    conn: sqlite3.Connection,
    *,
    notebook_id: str,
    kind: str,
    origin: str | None = None,
    title: str | None = None,
    content_hash: str | None = None,
    bytes_: int | None = None,
) -> SourceRecord:
    now = _now()
    rec_id = new_id()
    conn.execute(
        "INSERT INTO sources(id, notebook_id, kind, title, origin, content_hash, status, "
        "bytes, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            rec_id,
            notebook_id,
            kind,
            title,
            origin,
            content_hash,
            SourceStatus.PENDING.value,
            bytes_,
            now,
            now,
        ),
    )
    return get_source(conn, rec_id)


def get_source(conn: sqlite3.Connection, source_id: str) -> SourceRecord:
    row = conn.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
    if row is None:
        raise AppError(ErrorCode.STORAGE_NOT_FOUND, f"source {source_id} not found")
    return SourceRecord.from_row(row)


def list_sources(conn: sqlite3.Connection, *, notebook_id: str) -> list[SourceRecord]:
    rows = conn.execute(
        "SELECT * FROM sources WHERE notebook_id = ? ORDER BY created_at DESC",
        (notebook_id,),
    ).fetchall()
    return [SourceRecord.from_row(r) for r in rows]


def update_source_status(
    conn: sqlite3.Connection,
    source_id: str,
    *,
    status: SourceStatus,
    error_msg: str | None = None,
    error_remediation: str | None = None,
    page_count: int | None = None,
    chunk_count: int | None = None,
    title: str | None = None,
) -> SourceRecord:
    existing = get_source(conn, source_id)
    conn.execute(
        "UPDATE sources SET status=?, error_msg=?, error_remediation=?, "
        "page_count=?, chunk_count=?, "
        "title=COALESCE(?, title), updated_at=? WHERE id=?",
        (
            status.value,
            error_msg,
            error_remediation,
            page_count if page_count is not None else existing.page_count,
            chunk_count if chunk_count is not None else existing.chunk_count,
            title,
            _now(),
            source_id,
        ),
    )
    return get_source(conn, source_id)


def update_source_summary_status(
    conn: sqlite3.Connection,
    source_id: str,
    *,
    status: SummaryStatus | None,
) -> SourceRecord:
    """summary_status を更新する。None は「未生成」への復帰(中断時)。"""
    get_source(conn, source_id)
    conn.execute(
        "UPDATE sources SET summary_status=?, updated_at=? WHERE id=?",
        (status.value if status is not None else None, _now(), source_id),
    )
    return get_source(conn, source_id)


def update_source_summary(
    conn: sqlite3.Connection,
    source_id: str,
    *,
    summary: str,
) -> SourceRecord:
    """Persist the summary text and transition status to READY in one call."""
    get_source(conn, source_id)
    conn.execute(
        "UPDATE sources SET summary=?, summary_status=?, updated_at=? WHERE id=?",
        (summary, SummaryStatus.READY.value, _now(), source_id),
    )
    return get_source(conn, source_id)


def update_source_adr_status(
    conn: sqlite3.Connection,
    source_id: str,
    *,
    status: AdrStatus | None,
) -> SourceRecord:
    """ADR 抽出ジョブの状態だけ更新する(本文は変更しない)。None は未生成へ復帰。"""
    get_source(conn, source_id)
    conn.execute(
        "UPDATE sources SET adr_status=?, updated_at=? WHERE id=?",
        (status.value if status is not None else None, _now(), source_id),
    )
    return get_source(conn, source_id)


_TRANSIENT_SOURCE_STATUSES = (
    SourceStatus.PENDING,
    SourceStatus.PARSING,
    SourceStatus.CHUNKING,
    SourceStatus.EMBEDDING,
)

_INTERRUPTED_MSG = "サーバ再起動により処理が中断されました。「再試行」で再開できます。"


def reconcile_stale_sources(conn: sqlite3.Connection) -> dict[str, int]:
    """起動時に、前プロセスで中断されたジョブの status 残骸を整理する。

    起動直後はいかなるジョブも実行されていないことが保証されるため、
    遷移中 status は全て「中断された」ものとして倒す:

    - source.status: pending/parsing/chunking/embedding → error(中断メッセージ)
    - summary_status: generating → None(未生成)
    - adr_status: generating → None(未生成)

    これをしないと、UI 上は「入室しただけで変換/要約が勝手に走っている」
    ように見える(2026-07-04 実機フィードバック)。
    """
    now = _now()
    placeholders = ",".join("?" for _ in _TRANSIENT_SOURCE_STATUSES)
    cur = conn.execute(
        f"UPDATE sources SET status=?, error_msg=?, updated_at=? "
        f"WHERE status IN ({placeholders})",
        (
            SourceStatus.ERROR.value,
            _INTERRUPTED_MSG,
            now,
            *(s.value for s in _TRANSIENT_SOURCE_STATUSES),
        ),
    )
    n_sources = cur.rowcount
    cur = conn.execute(
        "UPDATE sources SET summary_status=NULL, updated_at=? WHERE summary_status=?",
        (now, SummaryStatus.GENERATING.value),
    )
    n_summaries = cur.rowcount
    cur = conn.execute(
        "UPDATE sources SET adr_status=NULL, updated_at=? WHERE adr_status=?",
        (now, AdrStatus.GENERATING.value),
    )
    n_adrs = cur.rowcount
    return {"sources": n_sources, "summaries": n_summaries, "adrs": n_adrs}


def update_source_adr(
    conn: sqlite3.Connection,
    source_id: str,
    *,
    draft: str,
    template: str,
    confidence: str,
) -> SourceRecord:
    """ADR 本文を保存し、status=READY と generated_at を一括設定する。"""
    get_source(conn, source_id)
    now = _now()
    conn.execute(
        "UPDATE sources SET adr_draft=?, adr_status=?, adr_template=?, "
        "adr_confidence=?, adr_generated_at=?, updated_at=? WHERE id=?",
        (
            draft,
            AdrStatus.READY.value,
            template,
            confidence,
            now,
            now,
            source_id,
        ),
    )
    return get_source(conn, source_id)


def update_source_adr_skipped(
    conn: sqlite3.Connection,
    source_id: str,
    *,
    reason: str,
    evidence: str | None = None,
) -> SourceRecord:
    """Decision Gate でスキップ判定された結果を保存する。

    `adr_draft` には reason / evidence を 1 行 JSON で詰める。フロントは
    `adr_status=='skipped'` のときだけこの JSON をパースする(API 層でデコード)。
    """
    import json as _json

    get_source(conn, source_id)
    now = _now()
    body = _json.dumps(
        {"adr_generated": False, "reason": reason, "evidence": evidence},
        ensure_ascii=False,
    )
    conn.execute(
        "UPDATE sources SET adr_draft=?, adr_status=?, adr_template=?, "
        "adr_confidence=?, adr_generated_at=?, updated_at=? WHERE id=?",
        (
            body,
            AdrStatus.SKIPPED.value,
            None,
            None,
            now,
            now,
            source_id,
        ),
    )
    return get_source(conn, source_id)


def clear_source_adr(conn: sqlite3.Connection, source_id: str) -> SourceRecord:
    """ADR 関連列を全て NULL に戻す(DELETE エンドポイントから呼ぶ)。"""
    get_source(conn, source_id)
    conn.execute(
        "UPDATE sources SET adr_draft=NULL, adr_status=NULL, adr_template=NULL, "
        "adr_confidence=NULL, adr_generated_at=NULL, updated_at=? WHERE id=?",
        (_now(), source_id),
    )
    return get_source(conn, source_id)


def update_source_title(
    conn: sqlite3.Connection,
    source_id: str,
    title: str,
) -> SourceRecord:
    get_source(conn, source_id)  # 存在チェック (無ければ STORAGE_NOT_FOUND)
    conn.execute(
        "UPDATE sources SET title=?, updated_at=? WHERE id=?",
        (title, _now(), source_id),
    )
    return get_source(conn, source_id)


def upsert_dedupe(
    conn: sqlite3.Connection,
    *,
    notebook_id: str,
    kind: str,
    content_hash: str,
    origin: str | None = None,
    title: str | None = None,
    bytes_: int | None = None,
) -> tuple[SourceRecord, bool]:
    """Return (record, was_new). If content_hash already exists in notebook, return existing."""
    row = conn.execute(
        "SELECT * FROM sources WHERE notebook_id = ? AND content_hash = ?",
        (notebook_id, content_hash),
    ).fetchone()
    if row is not None:
        return SourceRecord.from_row(row), False
    return (
        create_source(
            conn,
            notebook_id=notebook_id,
            kind=kind,
            origin=origin,
            title=title,
            content_hash=content_hash,
            bytes_=bytes_,
        ),
        True,
    )
