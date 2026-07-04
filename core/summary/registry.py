"""要約ジョブの実行中タスク登録簿。

source_id → asyncio.Task を追跡し、ユーザー操作(POST /summarize/cancel)で
実行中の SummaryJob をキャンセルできるようにする。

- 同一 source_id への再登録は上書き(再生成の連打では最後のタスクが正)。
- unregister はタスク一致時のみ削除(古いタスクの後始末が新タスクを消さない)。

設計メモ: 2026-07-04 実機フィードバック「要約を途中で中断するスイッチがない」。
"""
from __future__ import annotations

import asyncio


class SummaryTaskRegistry:
    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task] = {}

    def register(self, source_id: str, task: asyncio.Task) -> None:
        self._tasks[source_id] = task

    def unregister(self, source_id: str, task: asyncio.Task) -> None:
        if self._tasks.get(source_id) is task:
            del self._tasks[source_id]

    def cancel(self, source_id: str) -> bool:
        """実行中タスクがあればキャンセルして True。無ければ False。"""
        task = self._tasks.get(source_id)
        if task is None or task.done():
            return False
        task.cancel()
        return True

    def is_running(self, source_id: str) -> bool:
        task = self._tasks.get(source_id)
        return task is not None and not task.done()
