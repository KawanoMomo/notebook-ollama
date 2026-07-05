"""DevLogRing — 開発者モードのプロセス内リングバッファ。

仕様: docs/specs/2026-07-02-developer-mode-design.md §7

- バイト容量制。超過時は古い側から drop する(push 自体は常に成功、I10)
- seq はプロセス寿命で単調増加し、リング寿命中に重複しない(I1/I2/I7)
- clear() は entries を消すが next_seq は保持する(I3)
- resize() で縮小したときは即時 drop する(I4)
- disable() 後の push は 0 を返す no-op で stats も進めない(I5)
- 読み書きは threading.Lock で直列化する(I6)。read はロック内で
  スナップショットを作ってから返す
- size はエントリの JSON バイト長として push 時に確定する(NFR-6)
"""
from __future__ import annotations

import json
import threading
from collections import deque
from dataclasses import dataclass
from typing import Any, Literal

DEFAULT_CAPACITY_BYTES = 20 * 1024 * 1024
MIN_CAPACITY_BYTES = 1 * 1024 * 1024
MAX_CAPACITY_BYTES = 200 * 1024 * 1024


def clamp_capacity(value: int) -> int:
    """容量設定を 1MB..200MB にクランプする(仕様 §9.2 E7)。"""
    return max(MIN_CAPACITY_BYTES, min(MAX_CAPACITY_BYTES, int(value)))


@dataclass
class ReadResult:
    entries: list[dict]
    first_seq: int | None
    last_seq: int | None
    gap_before: bool
    gap_after: bool
    oldest_seq: int
    latest_seq: int


class DevLogRing:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: deque[dict] = deque()
        self._bytes = 0
        self._capacity = DEFAULT_CAPACITY_BYTES
        self._next_seq = 1
        self._dropped_total = 0
        self._enabled = False

    # ------------------------------------------------------------------
    # ライフサイクル
    # ------------------------------------------------------------------
    def enable(self, *, capacity_bytes: int) -> None:
        # クランプ(1MB..200MB)は設定層の責務(仕様 §9.2 E7)。リング自体は
        # 指定容量をそのまま使う(テスト・内部利用で小容量を許すため)。
        with self._lock:
            self._enabled = True
            self._capacity = max(1, int(capacity_bytes))
            self._drop_to_capacity_locked()

    def disable(self) -> None:
        with self._lock:
            self._enabled = False

    def resize(self, *, capacity_bytes: int) -> None:
        with self._lock:
            self._capacity = max(1, int(capacity_bytes))
            self._drop_to_capacity_locked()

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._bytes = 0

    # ------------------------------------------------------------------
    # 書き込み
    # ------------------------------------------------------------------
    def push(self, entry_without_seq: dict[str, Any]) -> int:
        """entry を追記して seq を返す。disabled のときは 0 を返す no-op。"""
        with self._lock:
            if not self._enabled:
                return 0
            seq = self._next_seq
            self._next_seq += 1
            entry = dict(entry_without_seq)
            entry["seq"] = seq
            try:
                size = len(json.dumps(entry, ensure_ascii=False).encode("utf-8"))
            except (TypeError, ValueError):
                # serialize 不能 payload は repr へ落とす(E1: push は失敗させない)
                entry["payload"] = {"repr": repr(entry.get("payload"))}
                size = len(json.dumps(entry, ensure_ascii=False).encode("utf-8"))
            entry["size"] = size
            self._entries.append(entry)
            self._bytes += size
            self._drop_to_capacity_locked()
            return seq

    def _drop_to_capacity_locked(self) -> None:
        while self._bytes > self._capacity and self._entries:
            dropped = self._entries.popleft()
            self._bytes -= dropped["size"]
            self._dropped_total += 1

    # ------------------------------------------------------------------
    # 読み出し
    # ------------------------------------------------------------------
    def read(
        self,
        *,
        after_seq: int | None = None,
        before_seq: int | None = None,
        limit: int = 500,
        order: Literal["asc", "desc"] = "asc",
    ) -> ReadResult:
        with self._lock:
            oldest = self._entries[0]["seq"] if self._entries else self._next_seq
            latest = self._entries[-1]["seq"] if self._entries else self._next_seq - 1
            selected = [
                e
                for e in self._entries
                if (after_seq is None or e["seq"] > after_seq)
                and (before_seq is None or e["seq"] < before_seq)
            ]
            if order == "desc":
                selected = selected[::-1]
            truncated = len(selected) > limit
            selected = selected[:limit]
            # 返却前にスナップショット(以後のロック外変更から独立)
            entries = [dict(e) for e in selected]

        first_seq = entries[0]["seq"] if entries else None
        last_seq = entries[-1]["seq"] if entries else None
        lo = min(first_seq, last_seq) if entries else None
        hi = max(first_seq, last_seq) if entries else None

        # gap_before: 要求範囲の古い側に drop 済みの範囲があるか。
        #   after_seq 指定で after_seq+1 < oldest ならその間は失われている。
        #   無指定でも oldest まで返しきれていなければ古い側に続きがある(=gap ではなく
        #   ページ続き)ため、gap は「drop により到達不能」の場合のみ True にする。
        gap_before = False
        if after_seq is not None and after_seq + 1 < oldest:
            gap_before = True
        elif entries and lo is not None and lo > oldest:
            gap_before = False  # まだページングで到達可能
        elif not entries and after_seq is not None and after_seq < oldest - 1:
            gap_before = True

        gap_after = bool(before_seq is not None and before_seq - 1 > latest)
        if truncated and order == "asc":
            gap_after = False  # 続きはページングで取得可能(失われてはいない)

        return ReadResult(
            entries=entries,
            first_seq=first_seq,
            last_seq=last_seq,
            gap_before=gap_before,
            gap_after=gap_after,
            oldest_seq=oldest,
            latest_seq=latest,
        )

    # ------------------------------------------------------------------
    # 概形
    # ------------------------------------------------------------------
    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def oldest_seq(self) -> int:
        with self._lock:
            return self._entries[0]["seq"] if self._entries else self._next_seq

    @property
    def latest_seq(self) -> int:
        with self._lock:
            return self._entries[-1]["seq"] if self._entries else self._next_seq - 1

    @property
    def next_seq(self) -> int:
        with self._lock:
            return self._next_seq

    @property
    def stats(self) -> dict[str, int | bool]:
        with self._lock:
            return {
                "enabled": self._enabled,
                "entries": len(self._entries),
                "bytes": self._bytes,
                "capacity_bytes": self._capacity,
                "dropped_total": self._dropped_total,
                "oldest_seq": self._entries[0]["seq"] if self._entries else self._next_seq,
                "latest_seq": self._entries[-1]["seq"] if self._entries else self._next_seq - 1,
                "next_seq": self._next_seq,
            }


# プロセス内 singleton(lifespan で enable/disable を制御する)
ring = DevLogRing()
