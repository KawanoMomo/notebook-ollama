import importlib
import pytest


@pytest.mark.parametrize("mod,sym", [
    ("core.recording.transcriber", "Transcriber"),
    ("core.recording.live_caption", "LiveCaption"),
    ("core.recording.agc", "apply_gain"),
    ("core.recording.levels", "LevelMeter"),
])
def test_recording_module_imports(mod, sym):
    try:
        m = importlib.import_module(mod)
    except ImportError as e:
        pytest.skip(f"recording extras not installed: {e}")
    assert hasattr(m, sym), f"{mod} missing {sym}"
