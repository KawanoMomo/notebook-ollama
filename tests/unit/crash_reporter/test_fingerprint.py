from core.crash_reporter.fingerprint import compute_fingerprint


def _raise_at(depth: int):
    if depth == 0:
        raise RuntimeError("boom")
    return _raise_at(depth - 1)


def test_same_traceback_yields_same_hash():
    try:
        _raise_at(2)
    except RuntimeError as e1:
        fp1 = compute_fingerprint(e1)
    try:
        _raise_at(2)
    except RuntimeError as e2:
        fp2 = compute_fingerprint(e2)
    assert fp1 == fp2


def test_different_exception_type_yields_different_hash():
    try:
        raise RuntimeError("x")
    except RuntimeError as e1:
        fp1 = compute_fingerprint(e1)
    try:
        raise ValueError("x")
    except ValueError as e2:
        fp2 = compute_fingerprint(e2)
    assert fp1 != fp2


def test_line_number_change_does_not_change_hash(monkeypatch):
    # 行番号を入れ替えても同じスタックトポロジなら同じハッシュであることを
    # 「同じ関数で 2 回 raise」で間接検証する。
    try:
        raise RuntimeError("a")
    except RuntimeError as e1:
        fp1 = compute_fingerprint(e1)
    try:
        raise RuntimeError("b")  # message が変わっても fp は変わらない
    except RuntimeError as e2:
        fp2 = compute_fingerprint(e2)
    assert fp1 == fp2  # 行番号は同じ、message は捨てているので一致


def test_returns_hex_sha1():
    try:
        raise RuntimeError("x")
    except RuntimeError as e:
        fp = compute_fingerprint(e)
    assert len(fp) == 40
    int(fp, 16)  # hex
