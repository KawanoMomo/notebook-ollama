from __future__ import annotations

import sqlite3
from dataclasses import dataclass

# 視覚索引の単位 (Stage 4)。'page' = 1ページ1ベクトル、'tile' = PixelRAG式。
DEFAULT_UNIT = "page"


@dataclass
class VisualIndexMeta:
    notebook_id: str
    embedding_model: str
    built_at: str
    # 末尾に既定値付きで追加 → 既存の位置引数での生成が壊れない
    unit: str = DEFAULT_UNIT


def upsert_meta(conn: sqlite3.Connection, meta: VisualIndexMeta) -> None:
    conn.execute(
        "INSERT INTO visual_index_meta(notebook_id, unit, embedding_model, built_at) "
        "VALUES (?, ?, ?, ?) ON CONFLICT(notebook_id, unit) DO UPDATE SET "
        "embedding_model=excluded.embedding_model, built_at=excluded.built_at",
        (meta.notebook_id, meta.unit, meta.embedding_model, meta.built_at),
    )


def get_meta(
    conn: sqlite3.Connection, notebook_id: str, unit: str = DEFAULT_UNIT
) -> VisualIndexMeta | None:
    row = conn.execute(
        "SELECT * FROM visual_index_meta WHERE notebook_id = ? AND unit = ?",
        (notebook_id, unit),
    ).fetchone()
    if row is None:
        return None
    return VisualIndexMeta(
        notebook_id=row["notebook_id"],
        embedding_model=row["embedding_model"],
        built_at=row["built_at"],
        unit=row["unit"],
    )


def delete_meta(
    conn: sqlite3.Connection, notebook_id: str, unit: str | None = None
) -> None:
    """メタと索引済みソース行を消す。

    unit=None は全単位削除。ノートブック削除・埋め込みモデル切替の既存呼び出しは
    「全部消える」前提で書かれているため、これを既定にする(page 既定にすると
    tile 索引が孤児として残る)。
    """
    if unit is None:
        conn.execute("DELETE FROM visual_index_meta WHERE notebook_id = ?", (notebook_id,))
        conn.execute(
            "DELETE FROM visual_index_sources WHERE notebook_id = ?", (notebook_id,)
        )
    else:
        conn.execute(
            "DELETE FROM visual_index_meta WHERE notebook_id = ? AND unit = ?",
            (notebook_id, unit),
        )
        conn.execute(
            "DELETE FROM visual_index_sources WHERE notebook_id = ? AND unit = ?",
            (notebook_id, unit),
        )


def mark_source_indexed(
    conn: sqlite3.Connection,
    *,
    notebook_id: str,
    source_id: str,
    page_count: int,
    built_at: str,
    unit: str = DEFAULT_UNIT,
) -> None:
    conn.execute(
        "INSERT INTO visual_index_sources(source_id, unit, notebook_id, page_count, built_at) "
        "VALUES (?, ?, ?, ?, ?) ON CONFLICT(source_id, unit) DO UPDATE SET "
        "notebook_id=excluded.notebook_id, page_count=excluded.page_count, "
        "built_at=excluded.built_at",
        (source_id, unit, notebook_id, page_count, built_at),
    )


def list_indexed_source_ids(
    conn: sqlite3.Connection, notebook_id: str, unit: str = DEFAULT_UNIT
) -> set[str]:
    rows = conn.execute(
        "SELECT source_id FROM visual_index_sources WHERE notebook_id = ? AND unit = ?",
        (notebook_id, unit),
    ).fetchall()
    return {r["source_id"] for r in rows}


def delete_indexed_source(
    conn: sqlite3.Connection, source_id: str, unit: str | None = None
) -> None:
    """unit=None はそのソースの全単位を削除(ソース削除・再取込の既定)。"""
    if unit is None:
        conn.execute("DELETE FROM visual_index_sources WHERE source_id = ?", (source_id,))
    else:
        conn.execute(
            "DELETE FROM visual_index_sources WHERE source_id = ? AND unit = ?",
            (source_id, unit),
        )
