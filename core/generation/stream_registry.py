"""生成ストリームの実行中会話を追跡する。

第2段(埋め込み)と翻訳は VRAM を生成と取り合うため、実行中は走らせない。
プロセス内メモリのみ。単一プロセス運用が前提(uvicorn --workers 1)。
"""

from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
from typing import Iterator

_running: Counter[str] = Counter()


def is_stream_running(conversation_id: str) -> bool:
    return _running[conversation_id] > 0


@contextmanager
def mark_running(conversation_id: str) -> Iterator[None]:
    _running[conversation_id] += 1
    try:
        yield
    finally:
        _running[conversation_id] -= 1
        if _running[conversation_id] <= 0:
            del _running[conversation_id]
