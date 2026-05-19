from pathlib import Path
from core.config import AppConfig

def test_app_config_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTEBOOK_OLLAMA_DATA_DIR", str(tmp_path))
    cfg = AppConfig()
    assert cfg.data_dir == tmp_path
    assert cfg.ollama.endpoint == "http://localhost:11434"
    assert cfg.ollama.embedding_model == "bge-m3"
    assert cfg.generation.context_budget_ratio == 0.8
    assert cfg.generation.response_budget_tokens == 1024
    assert cfg.retrieval.top_k == 8
    assert cfg.retrieval.top_k_max == 20
    assert cfg.retrieval.min_history_turns == 1
    assert cfg.server.host == "127.0.0.1"
    assert cfg.server.port == 8765
    assert cfg.mcp.enabled is True

def test_data_subdirs(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTEBOOK_OLLAMA_DATA_DIR", str(tmp_path))
    cfg = AppConfig()
    assert cfg.metadata_db_path == tmp_path / "metadata.db"
    assert cfg.qdrant_path == tmp_path / "qdrant"
    assert cfg.sources_dir == tmp_path / "sources"
    assert cfg.logs_dir == tmp_path / "logs"
    assert cfg.mcp_token_path == tmp_path / "mcp.token"

def test_ensure_dirs_creates_layout(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTEBOOK_OLLAMA_DATA_DIR", str(tmp_path / "nb"))
    cfg = AppConfig()
    cfg.ensure_dirs()
    assert (tmp_path / "nb").is_dir()
    assert (tmp_path / "nb" / "qdrant").is_dir()
    assert (tmp_path / "nb" / "sources").is_dir()
    assert (tmp_path / "nb" / "logs").is_dir()
