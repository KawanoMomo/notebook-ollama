import importlib

import pytest


def test_recorder_module_imports_symbols():
    try:
        m = importlib.import_module("core.recording.recorder")
    except ImportError as e:
        pytest.skip(f"recording extras not installed: {e}")
    for name in ("Recorder", "list_input_devices", "find_default_mic_index",
                 "find_default_loopback_index", "resolve_device_info"):
        assert hasattr(m, name), f"missing symbol: {name}"
