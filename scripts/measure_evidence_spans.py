"""第1段(字句照合)の解決率を実測する。Phase 1 ゲート用。

使い方:
    uv run --no-sync python scripts/measure_evidence_spans.py --data-dir ./.verify-data

本番 data_dir を指さないこと(隔離環境で実行する)。DB 名は core/config.py の
`metadata_db_path` に合わせて metadata.db。
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any

from core.generation.evidence_spans import summarize_resolution


def _load(db_path: Path) -> list[dict[str, Any]]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT content, citations FROM messages WHERE role='assistant' AND citations IS NOT NULL"
    ).fetchall()
    conn.close()
    return [{"answer": r["content"], "citations": json.loads(r["citations"])} for r in rows]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", required=True, type=Path)
    args = parser.parse_args()
    db = args.data_dir / "metadata.db"
    if not db.exists():
        raise SystemExit(f"metadata.db が見つかりません: {db}")
    print(json.dumps(summarize_resolution(_load(db)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
