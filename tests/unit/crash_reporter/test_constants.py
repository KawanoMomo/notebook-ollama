from core.crash_reporter import BLOCKED_LOG_KEYS, MAX_URL_LEN, REPO_SLUG


def test_repo_slug_matches_origin():
    assert REPO_SLUG == "KawanoMomo/notebook-ollama"


def test_max_url_len_safe_under_8kb():
    assert 6000 <= MAX_URL_LEN <= 7500  # GitHub 8KB - エンコード余白


def test_blocked_log_keys_contains_spec_listed():
    # spec §6.2 「通さない」リストの全項目を含むこと
    must = {
        "doc_id", "source_id", "chunk_id", "chunk_text", "text", "content",
        "embedding", "vector", "query", "question", "prompt", "response",
        "answer", "filename", "file_path", "title", "transcript",
        "audio_path", "user_input", "user_message", "messages", "documents",
    }
    assert must <= BLOCKED_LOG_KEYS
