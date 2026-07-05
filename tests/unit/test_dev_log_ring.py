"""DevLogRing のユニットテスト(仕様 §7 / §14、不変条件 I1〜I7・I10)。

開発者モードのコア: バイト容量制のプロセス内リングバッファ。
seq は単調増加でリング寿命中に重複せず、容量超過は古い側から drop する。
"""
from __future__ import annotations

import threading

import pytest

from core.dev_logs.ring import DevLogRing


def _mk(ring: DevLogRing, i: int, pad: int = 0) -> int:
    return ring.push(
        {
            "ts": f"2026-07-05T00:00:{i:02d}Z",
            "level": "info",
            "source": "app",
            "msg": f"m{i}" + ("x" * pad),
            "payload": {},
        }
    )


@pytest.fixture
def ring() -> DevLogRing:
    r = DevLogRing()
    r.enable(capacity_bytes=1024 * 1024)
    return r


def test_seq_is_gapless_and_monotonic(ring):
    seqs = [_mk(ring, i) for i in range(10)]
    assert seqs == list(range(seqs[0], seqs[0] + 10))
    assert ring.latest_seq == seqs[-1]
    assert ring.oldest_seq == seqs[0]


def test_drop_keeps_surviving_seqs_strictly_monotonic(ring):
    ring.resize(capacity_bytes=2048)
    for i in range(100):
        _mk(ring, i, pad=100)
    res = ring.read(limit=1000)
    seqs = [e["seq"] for e in res.entries]
    assert seqs == sorted(seqs)
    assert len(set(seqs)) == len(seqs)
    assert ring.stats["dropped_total"] > 0
    # 総バイトは容量以下(I10)
    assert ring.stats["bytes"] <= 2048


def test_read_after_dropped_seq_sets_gap_before(ring):
    ring.resize(capacity_bytes=1500)
    first = _mk(ring, 0, pad=100)
    for i in range(1, 60):
        _mk(ring, i, pad=100)
    assert ring.oldest_seq > first  # 先頭は drop 済み
    res = ring.read(after_seq=first)
    assert res.gap_before is True


def test_read_desc_paging_reaches_oldest(ring):
    seqs = [_mk(ring, i) for i in range(20)]
    page1 = ring.read(order="desc", limit=10)
    assert [e["seq"] for e in page1.entries] == list(reversed(seqs[10:]))
    page2 = ring.read(before_seq=page1.entries[-1]["seq"], order="desc", limit=10)
    assert [e["seq"] for e in page2.entries] == list(reversed(seqs[:10]))
    assert page2.entries[-1]["seq"] == ring.oldest_seq
    assert page2.gap_before is False


def test_clear_preserves_next_seq(ring):
    for i in range(5):
        _mk(ring, i)
    before = ring.next_seq
    ring.clear()
    assert ring.stats["entries"] == 0
    s = _mk(ring, 99)
    assert s == before  # 巻き戻らない(I3)


def test_resize_shrink_drops_immediately_and_grow_keeps(ring):
    for i in range(50):
        _mk(ring, i, pad=100)
    bytes_before = ring.stats["bytes"]
    ring.resize(capacity_bytes=1024)
    assert ring.stats["bytes"] <= 1024
    assert ring.stats["bytes"] < bytes_before
    n = ring.stats["entries"]
    ring.resize(capacity_bytes=1024 * 1024)
    assert ring.stats["entries"] == n  # 拡大で entries は増えない


def test_disabled_push_is_noop(ring):
    _mk(ring, 0)
    stats = dict(ring.stats)
    ring.disable()
    assert ring.push({"ts": "t", "level": "info", "source": "app", "msg": "x", "payload": {}}) == 0
    assert ring.stats["entries"] == stats["entries"]
    # I7: disable→enable で next_seq はリセットされない
    nxt = ring.next_seq
    ring.enable(capacity_bytes=4096)
    assert ring.next_seq == nxt


def test_concurrent_push_respects_capacity():
    ring = DevLogRing()
    ring.enable(capacity_bytes=64 * 1024)
    errors: list[Exception] = []

    def worker(tid: int) -> None:
        try:
            for i in range(200):
                ring.push(
                    {
                        "ts": "t",
                        "level": "info",
                        "source": "app",
                        "msg": f"t{tid}-{i}",
                        "payload": {"pad": "y" * 64},
                    }
                )
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert ring.stats["bytes"] <= 64 * 1024
    res = ring.read(limit=100000)
    seqs = [e["seq"] for e in res.entries]
    assert seqs == sorted(seqs)
    assert len(set(seqs)) == len(seqs)
