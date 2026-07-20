from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass


@dataclass
class MarkerRecord:
    id: str
    source_id: str
    kind: str   # 'page' 等
    value: str  # kind='page' ならページ番号の文字列
    at_ms: int  # 録音タイムライン上の時刻(live caption と同一 epoch 基準)

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "MarkerRecord":
        return cls(id=row["id"], source_id=row["source_id"], kind=row["kind"],
                   value=row["value"], at_ms=row["at_ms"])


def insert_markers(conn: sqlite3.Connection, markers: Iterable[MarkerRecord]) -> None:
    conn.executemany(
        "INSERT INTO source_markers (id, source_id, kind, value, at_ms)"
        " VALUES (?, ?, ?, ?, ?)",
        [(m.id, m.source_id, m.kind, m.value, m.at_ms) for m in markers],
    )


def list_markers(
    conn: sqlite3.Connection, source_id: str, kind: str | None = None
) -> list[MarkerRecord]:
    if kind is None:
        rows = conn.execute(
            "SELECT * FROM source_markers WHERE source_id = ? ORDER BY at_ms",
            (source_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM source_markers WHERE source_id = ? AND kind = ? ORDER BY at_ms",
            (source_id, kind),
        ).fetchall()
    return [MarkerRecord.from_row(r) for r in rows]
