from core.ollama.models_info import classify_recommendation, parse_context_window

def test_classify_recommendation_japanese_for_qwen():
    labels = classify_recommendation(
        name="qwen2.5:14b",
        family="qwen",
        parameter_size="14B",
        context_window=32768,
    )
    assert "japanese" in labels
    assert "general" in labels

def test_classify_recommendation_long_context():
    labels = classify_recommendation(
        name="gpt-oss:20b-128k",
        family="gpt-oss",
        parameter_size="20B",
        context_window=131072,
    )
    assert "long-context" in labels

def test_classify_recommendation_code():
    labels = classify_recommendation(
        name="qwen2.5-coder:7b",
        family="qwen",
        parameter_size="7B",
        context_window=16384,
    )
    assert "code" in labels

def test_parse_context_window_from_parameters_string():
    params = "num_ctx 32768\nstop \"</s>\""
    assert parse_context_window(params) == 32768

def test_parse_context_window_missing_returns_none():
    assert parse_context_window("stop foo") is None
