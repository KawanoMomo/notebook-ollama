import asyncio

from core.visual.encoder import run_idle_unload_watchdog


class CountingEncoder:
    def __init__(self):
        self.calls = 0

    def maybe_unload_if_idle(self) -> bool:
        self.calls += 1
        return False


class BoomEncoder:
    def __init__(self):
        self.calls = 0

    def maybe_unload_if_idle(self) -> bool:
        self.calls += 1
        raise RuntimeError("boom")


async def test_watchdog_fires_periodically():
    """回帰テスト: maybe_unload_if_idle の呼び出し箇所が構築ジョブの finally
    だけで、クエリ経路でロードされたエンコーダが解放されず常駐し続けていた
    (evaluator実機で確認、spec §7のアイドルアンロード未達)。"""
    enc = CountingEncoder()
    task = asyncio.create_task(run_idle_unload_watchdog(enc, interval_seconds=0.02))
    await asyncio.sleep(0.15)
    task.cancel()
    assert enc.calls >= 3


async def test_watchdog_survives_unload_exception():
    enc = BoomEncoder()
    task = asyncio.create_task(run_idle_unload_watchdog(enc, interval_seconds=0.02))
    await asyncio.sleep(0.15)
    task.cancel()
    assert enc.calls >= 3  # 例外で止まらず呼ばれ続ける
