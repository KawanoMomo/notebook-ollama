import importlib

import pytest


@pytest.mark.parametrize("mod,sym", [
    ("core.recording.diarizer", "SherpaDiarizer"),
    ("core.recording.embeddings", "SpeakerEmbedder"),
    ("core.recording.merger", "merge"),
])
def test_diarization_module_imports(mod, sym):
    try:
        m = importlib.import_module(mod)
    except ImportError as e:
        pytest.skip(f"recording extras not installed: {e}")
    assert hasattr(m, sym), f"{mod} missing {sym}"
