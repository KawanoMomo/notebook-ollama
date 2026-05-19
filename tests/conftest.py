from __future__ import annotations

import pytest


@pytest.fixture
def memory_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTEBOOK_OLLAMA_DATA_DIR", str(tmp_path))
    return tmp_path
