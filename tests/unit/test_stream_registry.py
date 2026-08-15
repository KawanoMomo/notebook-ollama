import pytest

from core.generation.stream_registry import is_stream_running, mark_running


def test_marks_and_clears():
    assert not is_stream_running("c1")
    with mark_running("c1"):
        assert is_stream_running("c1")
    assert not is_stream_running("c1")


def test_clears_on_exception():
    with pytest.raises(RuntimeError):
        with mark_running("c2"):
            raise RuntimeError("boom")
    assert not is_stream_running("c2")


def test_nested_marks_are_reference_counted():
    with mark_running("c3"):
        with mark_running("c3"):
            assert is_stream_running("c3")
        assert is_stream_running("c3")
    assert not is_stream_running("c3")


def test_other_conversation_is_unaffected():
    with mark_running("c4"):
        assert not is_stream_running("c5")
