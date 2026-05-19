from core.tokens import count_tokens


def test_count_tokens_simple_ascii():
    assert count_tokens("hello world") > 0
    assert count_tokens("") == 0


def test_count_tokens_japanese():
    n = count_tokens("これはテストです。")
    assert n > 0


def test_count_tokens_caches_encoder():
    a = count_tokens("the quick brown fox")
    b = count_tokens("the quick brown fox")
    assert a == b
