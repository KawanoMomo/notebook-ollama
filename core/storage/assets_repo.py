from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass


@dataclass
class AssetRecord:
    id: str
    source_id: str
    chunk_id: str | None
    kind: str  # 'table' | 'figure'
    page: int | None
    bbox_json: str | None
    html: str | None
    md_snippet: str | None
    image_path: str | None
    created_at: str
    desc_chunk_id: str | None = None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> AssetRecord:
        keys = row.keys()
        return cls(
            id=row["id"],
            source_id=row["source_id"],
            chunk_id=row["chunk_id"],
            kind=row["kind"],
            page=row["page"],
            bbox_json=row["bbox_json"],
            html=row["html"],
            md_snippet=row["md_snippet"],
            image_path=row["image_path"],
            created_at=row["created_at"],
            desc_chunk_id=row["desc_chunk_id"] if "desc_chunk_id" in keys else None,
        )


def insert_assets(conn: sqlite3.Connection, assets: Iterable[AssetRecord]) -> None:
    conn.executemany(
        "INSERT INTO chunk_assets(id, source_id, chunk_id, kind, page, bbox_json, "
        "html, md_snippet, image_path, created_at, desc_chunk_id) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        [(a.id, a.source_id, a.chunk_id, a.kind, a.page, a.bbox_json,
          a.html, a.md_snippet, a.image_path, a.created_at, a.desc_chunk_id) for a in assets],
    )


def list_assets_for_source(conn: sqlite3.Connection, source_id: str) -> list[AssetRecord]:
    rows = conn.execute(
        "SELECT * FROM chunk_assets WHERE source_id = ? ORDER BY page, id", (source_id,)
    ).fetchall()
    return [AssetRecord.from_row(r) for r in rows]


def list_assets_for_chunk_ids(
    conn: sqlite3.Connection, chunk_ids: list[str]
) -> dict[str, list[AssetRecord]]:
    if not chunk_ids:
        return {}
    placeholders = ",".join("?" * len(chunk_ids))
    rows = conn.execute(
        f"SELECT * FROM chunk_assets WHERE chunk_id IN ({placeholders})",  # noqa: S608
        chunk_ids,
    ).fetchall()
    out: dict[str, list[AssetRecord]] = {}
    for r in rows:
        out.setdefault(r["chunk_id"], []).append(AssetRecord.from_row(r))
    return out


def list_assets_for_desc_chunk_ids(
    conn: sqlite3.Connection, desc_chunk_ids: list[str]
) -> dict[str, AssetRecord]:
    """figure_desc チャンクID → そのチャンクを生んだ図アセット(1件、画像取得用)。"""
    if not desc_chunk_ids:
        return {}
    placeholders = ",".join("?" * len(desc_chunk_ids))
    rows = conn.execute(
        f"SELECT * FROM chunk_assets WHERE desc_chunk_id IN ({placeholders})",  # noqa: S608
        desc_chunk_ids,
    ).fetchall()
    return {r["desc_chunk_id"]: AssetRecord.from_row(r) for r in rows}


def set_chunk_link(conn: sqlite3.Connection, asset_id: str, chunk_id: str) -> None:
    conn.execute("UPDATE chunk_assets SET chunk_id = ? WHERE id = ?", (chunk_id, asset_id))


def set_desc_chunk_link(conn: sqlite3.Connection, asset_id: str, desc_chunk_id: str) -> None:
    conn.execute(
        "UPDATE chunk_assets SET desc_chunk_id = ? WHERE id = ?", (desc_chunk_id, asset_id)
    )


def delete_assets_for_source(conn: sqlite3.Connection, source_id: str) -> None:
    conn.execute("DELETE FROM chunk_assets WHERE source_id = ?", (source_id,))
