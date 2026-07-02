"""例外のスタックトポロジから fingerprint を計算する (重複 Issue 抑制用)。"""
from __future__ import annotations

import hashlib
import traceback


def compute_fingerprint(exc: BaseException) -> str:
    """例外型 + (module, function) フレーム列の SHA1 を返す。

    - 行番号は意図的に捨てる: 周辺コードの編集で fingerprint が変わると
      「同じバグ」を再報告してしまう。
    - メッセージ本文も捨てる: 同じバグでも入力依存で本文が変わるため。
    """
    cls = type(exc)
    parts: list[str] = [f"{cls.__module__}.{cls.__qualname__}"]
    tb = exc.__traceback__
    for frame in traceback.extract_tb(tb):
        # frame.filename はフルパス。モジュール末尾名のみで安定化。
        module = frame.filename.replace("\\", "/").rsplit("/", 1)[-1]
        parts.append(f"{module}::{frame.name}")
    # SHA1 は非暗号目的の dedup hash として使用 (重複 Issue 抑制のみ)。
    digest = hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()  # noqa: S324
    return digest
