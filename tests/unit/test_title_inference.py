import asyncio

from core.recording.title_inference import (
    build_title_prompt,
    infer_title,
    parse_title,
)


def test_build_prompt_includes_text_and_instruction():
    segs = [{"speaker": "あなた", "text": "来期の予算について"},
            {"speaker": "相手1", "text": "資料を共有します"}]
    prompt = build_title_prompt(segs)
    assert "来期の予算について" in prompt
    assert "資料を共有します" in prompt
    assert "タイトル" in prompt


def test_build_prompt_truncates_long_text():
    segs = [{"speaker": "あなた", "text": "あ" * 5000}]
    prompt = build_title_prompt(segs)
    # 本文は打ち切られる(プロンプト全体が原文5000字を丸ごと含まない)。
    assert prompt.count("あ") < 5000


def test_parse_strips_quotes_and_preamble():
    assert parse_title('「来期予算レビュー会議」') == "来期予算レビュー会議"
    assert parse_title('"Q3 Planning"') == "Q3 Planning"
    assert parse_title("タイトル: 採用面談の振り返り") == "採用面談の振り返り"


def test_parse_takes_first_nonempty_line():
    assert parse_title("\n\n  プロジェクト定例  \n補足説明") == "プロジェクト定例"


def test_parse_empty_returns_empty():
    assert parse_title("") == ""
    assert parse_title("   \n  ") == ""


def test_infer_title_returns_parsed_title():
    class _LLM:
        async def generate(self, *, model, prompt, options=None):
            return "「来期予算レビュー」"

    segs = [{"speaker": "あなた", "text": "来期の予算を見直したい"}]
    out = asyncio.run(infer_title(segs, _LLM(), "qwen2.5:14b"))
    assert out == "来期予算レビュー"


def test_infer_title_empty_segments_returns_empty():
    class _LLM:
        async def generate(self, *, model, prompt, options=None):
            raise AssertionError("LLM must not be called for empty segments")

    assert asyncio.run(infer_title([], _LLM(), "qwen2.5:14b")) == ""


def test_infer_title_swallows_llm_exception():
    class _BoomLLM:
        async def generate(self, *, model, prompt, options=None):
            raise RuntimeError("boom")

    segs = [{"speaker": "あなた", "text": "x"}]
    assert asyncio.run(infer_title(segs, _BoomLLM(), "qwen2.5:14b")) == ""
