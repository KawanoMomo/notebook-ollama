"""golden set (評価用の正解データ) の読み書き。

1行1問の JSONL。正解チャンクの本文を reference_contexts に持たせることで、
採点を文字列類似度だけで完結させ、judge LLM への依存を排除する
(spec §2.3)。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

# 図表RAGの効果を種別ごとに分解して見るための分類 (spec §5.1)
VALID_KINDS = frozenset({"text", "table", "figure"})


class GoldenSetError(Exception):
    """golden set の形式が不正。"""


@dataclass(frozen=True)
class GoldenItem:
    id: str
    question: str
    reference_contexts: list[str]
    kind: str
    page_no: int | None = None


def load_golden(path: Path) -> list[GoldenItem]:
    items: list[GoldenItem] = []
    seen: set[str] = set()

    for lineno, raw in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        try:
            row = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise GoldenSetError(f"{path}:{lineno} JSON として読めない: {exc}") from exc

        item = _build_item(row, path=path, lineno=lineno)
        if item.id in seen:
            raise GoldenSetError(f"{path}:{lineno} id が重複している: {item.id}")
        seen.add(item.id)
        items.append(item)

    return items


def _build_item(row: dict, *, path: Path, lineno: int) -> GoldenItem:
    where = f"{path}:{lineno}"

    for key in ("id", "question", "reference_contexts", "kind"):
        if key not in row:
            raise GoldenSetError(f"{where} 必須フィールドが無い: {key}")

    kind = row["kind"]
    if kind not in VALID_KINDS:
        raise GoldenSetError(
            f"{where} kind が不正: {kind!r} (許可: {sorted(VALID_KINDS)})"
        )

    contexts = row["reference_contexts"]
    if not isinstance(contexts, list) or not contexts:
        raise GoldenSetError(f"{where} reference_contexts が空、または配列でない")
    if any(not isinstance(c, str) or not c.strip() for c in contexts):
        raise GoldenSetError(f"{where} reference_contexts に空文字列が含まれる")

    return GoldenItem(
        id=str(row["id"]),
        question=str(row["question"]),
        reference_contexts=[str(c) for c in contexts],
        kind=kind,
        page_no=row.get("page_no"),
    )


def dump_golden(items: list[GoldenItem], path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(asdict(i), ensure_ascii=False) for i in items]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
