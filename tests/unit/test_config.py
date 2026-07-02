from pathlib import Path

from core.config import AppConfig, OllamaSettings


def test_ollama_chat_read_timeout_default():
    # 大型モデル(GPT-OSS:20B 等)の初回ロードを許容する 600s 保険値。
    assert OllamaSettings().chat_read_timeout_seconds == 600.0


def test_ollama_request_timeout_default():
    assert OllamaSettings().request_timeout_seconds == 600.0


def test_ollama_chat_read_timeout_env_override(monkeypatch):
    monkeypatch.setenv("NOTEBOOK_OLLAMA_OLLAMA__CHAT_READ_TIMEOUT_SECONDS", "30")
    cfg = AppConfig()
    assert cfg.ollama.chat_read_timeout_seconds == 30.0


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
    # crash_report: 初期は未決定 (None) + 自動オプトインプロンプト有効。
    assert cfg.crash_report.enabled is None
    assert cfg.crash_report.auto_prompt is True
    assert cfg.crash_report.opted_in_at is None


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


# -----------------------------------------------------------------------------
# Sprint 3 / Task 3.3: crash-report 関連パス
#
# spec §4 / §7.2 で前提となる ``crash-pending/`` ディレクトリ, ``reported.txt``,
# ``running.lock`` を ``AppConfig`` 経由で発見できるようにする。``notices.json``
# は plan Task 3.7 で app-bundled (リポジトリ同梱) として扱うため、``AppConfig``
# 側も同じ場所を返す。
# -----------------------------------------------------------------------------


def test_crash_pending_dir_default(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTEBOOK_OLLAMA_DATA_DIR", str(tmp_path))
    cfg = AppConfig()
    assert cfg.crash_pending_dir == tmp_path / "crash-pending"
    assert isinstance(cfg.crash_pending_dir, Path)


def test_reported_path_default(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTEBOOK_OLLAMA_DATA_DIR", str(tmp_path))
    cfg = AppConfig()
    assert cfg.reported_path == tmp_path / "reported.txt"
    assert isinstance(cfg.reported_path, Path)


def test_running_lock_path_default(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTEBOOK_OLLAMA_DATA_DIR", str(tmp_path))
    cfg = AppConfig()
    assert cfg.running_lock_path == tmp_path / "running.lock"
    assert isinstance(cfg.running_lock_path, Path)


def test_notices_path_is_app_bundled(tmp_path, monkeypatch):
    """``notices.json`` はリポジトリ同梱なので data_dir 変更で動かない。"""
    monkeypatch.setenv("NOTEBOOK_OLLAMA_DATA_DIR", str(tmp_path))
    cfg = AppConfig()
    assert isinstance(cfg.notices_path, Path)
    assert cfg.notices_path.name == "notices.json"
    # data_dir 配下ではないこと (= app-bundled パス)。
    assert tmp_path not in cfg.notices_path.parents
    # 末尾2階層は data/notices.json で固定。
    assert cfg.notices_path.parent.name == "data"


def test_ensure_dirs_creates_crash_pending_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTEBOOK_OLLAMA_DATA_DIR", str(tmp_path / "nb"))
    cfg = AppConfig()
    cfg.ensure_dirs()
    assert cfg.crash_pending_dir.is_dir()


def test_ensure_dirs_is_idempotent(tmp_path, monkeypatch):
    """ensure_dirs を 2 度呼んでもエラーにならない (`exist_ok=True`)。"""
    monkeypatch.setenv("NOTEBOOK_OLLAMA_DATA_DIR", str(tmp_path / "nb"))
    cfg = AppConfig()
    cfg.ensure_dirs()
    cfg.ensure_dirs()  # should not raise FileExistsError
    assert cfg.crash_pending_dir.is_dir()


def test_data_dir_env_override_propagates_to_crash_paths(tmp_path, monkeypatch):
    """``NOTEBOOK_OLLAMA_DATA_DIR`` 上書きが crash 関連パスにも波及する。"""
    custom = tmp_path / "custom_data"
    monkeypatch.setenv("NOTEBOOK_OLLAMA_DATA_DIR", str(custom))
    cfg = AppConfig()
    assert cfg.crash_pending_dir == custom / "crash-pending"
    assert cfg.reported_path == custom / "reported.txt"
    assert cfg.running_lock_path == custom / "running.lock"


def test_ensure_dirs_does_not_create_files(tmp_path, monkeypatch):
    """``reported.txt`` / ``running.lock`` / ``notices.json`` は file なので
    ensure_dirs では作らない (作ると mkdir が壊れるし意味的に file)。"""
    monkeypatch.setenv("NOTEBOOK_OLLAMA_DATA_DIR", str(tmp_path / "nb"))
    cfg = AppConfig()
    cfg.ensure_dirs()
    assert not cfg.reported_path.exists()
    assert not cfg.running_lock_path.exists()
