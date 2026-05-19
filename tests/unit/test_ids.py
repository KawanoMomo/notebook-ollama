import re

from core.ids import new_id


def test_new_id_returns_26_char_ulid():
    value = new_id()
    assert isinstance(value, str)
    assert len(value) == 26
    assert re.fullmatch(r"[0-9A-HJKMNP-TV-Z]{26}", value)


def test_new_id_is_unique_across_calls():
    values = {new_id() for _ in range(100)}
    assert len(values) == 100


def test_new_id_sorts_chronologically():
    a = new_id()
    b = new_id()
    assert a < b
