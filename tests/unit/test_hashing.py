from core.ingestion.hashing import sha256_bytes, sha256_text

def test_sha256_bytes_deterministic():
    a = sha256_bytes(b"hello")
    b = sha256_bytes(b"hello")
    assert a == b
    assert len(a) == 64

def test_sha256_bytes_differs_per_input():
    assert sha256_bytes(b"a") != sha256_bytes(b"b")

def test_sha256_text_uses_utf8():
    assert sha256_text("こんにちは") == sha256_bytes("こんにちは".encode("utf-8"))
