import asyncio
import contextlib

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


async def _run_until_calls(enc, target: int, *, max_yields: int = 10_000) -> None:
    """ウォッチドッグを目標発火回数までイベントループ上で回す。

    以前は interval_seconds=0.02 のウォッチドッグを 0.15 秒スリープして観測して
    いたが、Windows の asyncio タイマー粒度(約15.6ms)により実際の発火が 2 回に
    留まり `assert calls >= 3` が落ちることがあった(他テストと同時実行したとき
    に再現。torch のロード有無とは無関係)。壁時計ではなくイベントループの
    ターン数で回して決定的にする。
    """
    task = asyncio.create_task(run_idle_unload_watchdog(enc, interval_seconds=0))
    try:
        for _ in range(max_yields):
            if enc.calls >= target:
                return
            await asyncio.sleep(0)
        raise AssertionError(
            f"watchdog fired {enc.calls} times in {max_yields} yields, expected >= {target}"
        )
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


async def test_watchdog_fires_periodically():
    """回帰テスト: maybe_unload_if_idle の呼び出し箇所が構築ジョブの finally
    だけで、クエリ経路でロードされたエンコーダが解放されず常駐し続けていた
    (evaluator実機で確認、spec §7のアイドルアンロード未達)。"""
    enc = CountingEncoder()
    await _run_until_calls(enc, 3)
    assert enc.calls >= 3


async def test_watchdog_survives_unload_exception():
    enc = BoomEncoder()
    await _run_until_calls(enc, 3)
    assert enc.calls >= 3  # 例外で止まらず呼ばれ続ける
