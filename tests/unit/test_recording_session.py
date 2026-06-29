from pathlib import Path

import pytest

from core.recording.session import RecordingBusyError, RecordingRegistry


class _FakeRecorder:
    def __init__(self):
        self.started = False
        self.stopped = False
    def start(self, **k):
        self.started = True
    def stop(self):
        self.stopped = True
        return {"mic": None, "system": None}


def test_single_instance_guard():
    reg = RecordingRegistry()
    s1 = reg.start("nb", Path("/tmp/a"), lambda: _FakeRecorder())
    assert reg.active_id == s1.id
    with pytest.raises(RecordingBusyError):
        reg.start("nb", Path("/tmp/b"), lambda: _FakeRecorder())


def test_pop_clears_active():
    reg = RecordingRegistry()
    s1 = reg.start("nb", Path("/tmp/a"), lambda: _FakeRecorder())
    popped = reg.pop(s1.id)
    assert popped is s1
    assert reg.active_id is None
    s2 = reg.start("nb", Path("/tmp/b"), lambda: _FakeRecorder())
    assert reg.active_id == s2.id


def test_get_returns_session_and_extras_isolated():
    reg = RecordingRegistry()
    s1 = reg.start("nb", Path("/tmp/a"), lambda: _FakeRecorder())
    assert reg.get(s1.id) is s1
    s1.extras["k"] = "v"
    assert reg.get(s1.id).extras["k"] == "v"
    assert reg.get("nonexistent") is None
