from core.features import get_flag, is_enabled
from core.generation.prompts import (
    SYSTEM_PROMPT,
    build_system_prompt,
    sentence_id_instruction,
)


def test_all_betas_off_keeps_prompt_byte_identical():
    assert build_system_prompt(quote_mode=False, sentence_id_mode=False) == SYSTEM_PROMPT


def test_sentence_id_on_appends_only_its_instruction():
    got = build_system_prompt(quote_mode=False, sentence_id_mode=True)
    assert got == SYSTEM_PROMPT + sentence_id_instruction()


def test_instruction_shows_the_expected_format():
    text = sentence_id_instruction()
    assert "[^1:C12]" in text
    assert "<C1>" in text


def test_flag_is_registered_as_beta_and_off_by_default():
    flag = get_flag("citation-sentence-id")
    assert flag is not None
    assert flag.stage == "beta"
    assert is_enabled("citation-sentence-id", {}) is False
