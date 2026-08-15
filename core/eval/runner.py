"""条件の逐次実行。失敗継続と中断再開を担う (spec §7)。

検索の実行そのものは呼び出し側が SearchFn として注入する。この層は
本番サービスを import しないので、フェイクを差し込んでユニットテストできる。
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from core.eval.goldenset import GoldenItem
from core.eval.matrix import Condition
from core.logging import get_logger

log = get_logger("eval.runner")


class ConditionFailed(Exception):
    """この条件は実行不能。スイープ全体は続行する。

    ADR-016 の pixel_native 明示エラーなど、意図的な失敗をここに集約する。
    """


class SearchFn(Protocol):
    async def __call__(
        self, *, condition: Condition, item: GoldenItem
    ) -> list[str]: ...


def completed_condition_ids(results_path: Path) -> set[str]:
    """すでに実行が完了した条件ID (成功・失敗の両方)。"""
    path = Path(results_path)
    if not path.exists():
        return set()

    done: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            # 中断時に行が途中で切れることがある。読めない行は無視する。
            continue
        if row.get("type") == "condition":
            done.add(row["condition_id"])
    return done


def _append(path: Path, row: dict) -> None:
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        fh.flush()


async def run_sweep(
    *,
    conditions: list[Condition],
    golden: list[GoldenItem],
    search: SearchFn,
    results_path: Path,
    now: Callable[[], float] = time.monotonic,
) -> None:
    path = Path(results_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    done = completed_condition_ids(path)

    for condition in conditions:
        if condition.id in done:
            log.info("condition_skipped", condition_id=condition.id)
            continue

        started = now()
        failed_reason: str | None = None
        rows: list[dict] = []

        try:
            for item in golden:
                retrieved = await search(condition=condition, item=item)
                rows.append(
                    {
                        "type": "question",
                        "condition_id": condition.id,
                        "question_id": item.id,
                        "kind": item.kind,
                        "retrieved_contexts": list(retrieved),
                        "reference_contexts": list(item.reference_contexts),
                    }
                )
        except ConditionFailed as exc:
            failed_reason = str(exc)
        except Exception as exc:  # noqa: BLE001 — OOM 等も条件失敗として扱う
            failed_reason = f"{type(exc).__name__}: {exc}"
            log.warning(
                "condition_crashed", condition_id=condition.id, error=str(exc)
            )

        # 質問行は条件マーカーより先に書く。マーカーが「この条件は完了」の
        # 唯一の印なので、途中で落ちたら次回は最初からやり直しになる。
        if failed_reason is None:
            for row in rows:
                _append(path, row)

        _append(
            path,
            {
                "type": "condition",
                "condition_id": condition.id,
                "overrides": condition.overrides,
                "elapsed_s": now() - started,
                "failed_reason": failed_reason,
            },
        )
