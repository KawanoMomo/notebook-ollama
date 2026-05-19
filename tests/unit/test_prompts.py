from core.generation.prompts import (
    SYSTEM_PROMPT,
    build_user_prompt,
    PromptChunk,
)

def test_system_prompt_mentions_citations_and_japanese():
    assert "[^" in SYSTEM_PROMPT
    assert "日本語" in SYSTEM_PROMPT

def test_build_user_prompt_includes_sources_xml_and_question():
    chunks = [
        PromptChunk(n=1, title="ARM", location="p.42", text="body 1"),
        PromptChunk(n=2, title="Memo", location="§3.2", text="body 2"),
    ]
    prompt = build_user_prompt(chunks=chunks, question="how many priorities?")
    assert '<source id="1"' in prompt
    assert 'title="ARM"' in prompt
    assert "body 1" in prompt
    assert '<source id="2"' in prompt
    assert "body 2" in prompt
    assert "how many priorities?" in prompt

def test_build_user_prompt_no_chunks_section_when_empty():
    prompt = build_user_prompt(chunks=[], question="orphan question")
    assert "<sources></sources>" in prompt
