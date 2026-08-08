from core.generation.prompts import SYSTEM_PROMPT, build_system_prompt, quote_mode_instruction


def test_off_keeps_system_prompt_byte_identical():
    assert build_system_prompt(quote_mode=False) == SYSTEM_PROMPT


def test_on_appends_instruction():
    got = build_system_prompt(quote_mode=True)
    assert got.startswith(SYSTEM_PROMPT)
    assert quote_mode_instruction() in got


def test_instruction_mentions_the_tag():
    assert "<q>" in quote_mode_instruction()


def test_flag_is_registered_as_beta():
    from core.features import get_flag, is_enabled

    flag = get_flag("citation-quote-mode")
    assert flag is not None
    assert flag.stage == "beta"
    # 既定(オプトイン無し)では無効
    assert is_enabled("citation-quote-mode", {}) is False
    assert is_enabled("citation-quote-mode", {"citation-quote-mode": True}) is True
