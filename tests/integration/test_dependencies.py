from core.config import AppConfig
from apps.api.dependencies import build_context


def test_build_context_wires_chat_read_timeout(tmp_path):
    cfg = AppConfig(data_dir=tmp_path)
    cfg.ollama.chat_read_timeout_seconds = 45.0
    ctx = build_context(cfg)
    # OllamaGateway は raw client を保持する
    assert ctx.ollama._client._chat_read_timeout == 45.0
