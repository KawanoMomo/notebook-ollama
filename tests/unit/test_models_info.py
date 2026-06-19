from core.ollama.models_info import (
    classify_kind,
    classify_recommendation,
    parse_context_window,
)


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
    params = 'num_ctx 32768\nstop "</s>"'
    assert parse_context_window(params) == 32768


def test_parse_context_window_missing_returns_none():
    assert parse_context_window("stop foo") is None


def test_classify_kind_capabilities_embedding_wins_over_name():
    # capabilities が一次情報。名前が chat 風でも capabilities を優先。
    assert (
        classify_kind(capabilities=["embedding"], name="qwen2.5:14b")
        == "embedding"
    )


def test_classify_kind_capabilities_completion_is_chat():
    assert (
        classify_kind(capabilities=["completion"], name="anything") == "chat"
    )


def test_classify_kind_capabilities_chat_is_chat():
    assert classify_kind(capabilities=["chat"], name="anything") == "chat"


def test_classify_kind_capabilities_both():
    assert (
        classify_kind(capabilities=["completion", "embedding"], name="foo")
        == "both"
    )


def test_classify_kind_fallback_embedding_by_name():
    # capabilities 空 → 名前ヒューリスティック。
    assert classify_kind(capabilities=[], name="bge-m3") == "embedding"
    assert (
        classify_kind(capabilities=[], name="nomic-embed-text") == "embedding"
    )
    assert (
        classify_kind(capabilities=[], name="mxbai-embed-large") == "embedding"
    )
    assert (
        classify_kind(capabilities=[], name="snowflake-arctic-embed:l")
        == "embedding"
    )
    assert classify_kind(capabilities=[], name="all-minilm") == "embedding"


def test_classify_kind_fallback_chat_by_default():
    assert classify_kind(capabilities=[], name="qwen2.5:14b") == "chat"


def test_classify_kind_unknown_when_no_signal():
    # capabilities 空 かつ name も空 → 判定不能。
    assert classify_kind(capabilities=[], name="") == "unknown"
