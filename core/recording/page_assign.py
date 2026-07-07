"""録音チャンクへの発表ページ割当(spec §4)。

録音ソースのチャンクにおける page の意味は「親発表資料の何ページ目で
話したか」。at_ms 昇順の page マーカー列に対し、チャンク開始時刻以前の
最後のマーカーのページを返す(発表開始前の無音等、最初のマーカーより
前は None)。
"""
from __future__ import annotations

import bisect


def page_for(start_ms: int | None, page_markers: list[tuple[int, int]]) -> int | None:
    if start_ms is None or not page_markers:
        return None
    times = [t for t, _ in page_markers]
    idx = bisect.bisect_right(times, start_ms) - 1
    if idx < 0:
        return None
    return page_markers[idx][1]
