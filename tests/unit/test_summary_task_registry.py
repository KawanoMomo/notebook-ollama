"""SummaryTaskRegistry のユニットテスト。

要約ジョブの実行中タスクを source_id で追跡し、ユーザー操作でキャンセル
できるようにする(2026-07-04 実機フィードバック: 中断スイッチが無い)。
"""
from __future__ import annotations

import asyncio

import pytest

from core.summary.registry import SummaryTaskRegistry


@pytest.mark.asyncio
async def test_cancel_running_task_returns_true_and_cancels():
    reg = SummaryTaskRegistry()
    started = asyncio.Event()

    async def _long_job():
        started.set()
        await asyncio.sleep(60)

    task = asyncio.create_task(_long_job())
    reg.register("src1", task)
    await started.wait()

    assert reg.cancel("src1") is True
    with pytest.raises(asyncio.CancelledError):
        await task
    assert task.cancelled()


@pytest.mark.asyncio
async def test_cancel_unknown_source_returns_false():
    reg = SummaryTaskRegistry()
    assert reg.cancel("nope") is False


@pytest.mark.asyncio
async def test_cancel_done_task_returns_false():
    reg = SummaryTaskRegistry()

    async def _quick():
        return None

    task = asyncio.create_task(_quick())
    reg.register("src1", task)
    await task
    assert reg.cancel("src1") is False


@pytest.mark.asyncio
async def test_unregister_removes_only_matching_task():
    reg = SummaryTaskRegistry()

    async def _sleep():
        await asyncio.sleep(60)

    t1 = asyncio.create_task(_sleep())
    t2 = asyncio.create_task(_sleep())
    reg.register("src1", t1)
    # 別タスクで上書き(再生成の連打相当)
    reg.register("src1", t2)
    # 古いタスクの unregister は現行登録を消さない
    reg.unregister("src1", t1)
    assert reg.cancel("src1") is True  # t2 がキャンセルされる

    t1.cancel()
    for t in (t1, t2):
        with pytest.raises(asyncio.CancelledError):
            await t
