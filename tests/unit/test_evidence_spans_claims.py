from core.generation.evidence_spans import (
    ClaimOccurrence,
    iter_claim_occurrences,
    mask_code_regions,
)


def test_mask_code_regions_preserves_offsets():
    src = "前置き `[^9]` 後置き"
    masked = mask_code_regions(src)
    assert len(masked) == len(src)
    assert "[^9]" not in masked
    assert masked.startswith("前置き ")


def test_mask_code_regions_masks_fenced_block():
    src = "説明\n```python\nx = a[^1]\n```\n本文[^2]。"
    masked = mask_code_regions(src)
    assert len(masked) == len(src)
    assert masked.count("[^1]") == 0
    assert masked.count("[^2]") == 1


def test_iter_claim_occurrences_numbers_each_occurrence():
    answer = "レベル1は成果の達成を示す[^3]。レベル2では成果物が管理される[^3]。"
    got = iter_claim_occurrences(answer)
    assert [(c.n, c.answer_occurrence) for c in got] == [(3, 0), (3, 1)]
    assert got[0].claim == "レベル1は成果の達成を示す"
    assert got[1].claim == "レベル2では成果物が管理される"


def test_iter_claim_occurrences_strips_markers_from_claim():
    answer = "AはBである[^1][^2]。"
    got = iter_claim_occurrences(answer)
    assert all("[^" not in c.claim for c in got)
    assert [(c.n, c.answer_occurrence) for c in got] == [(1, 0), (2, 1)]


def test_iter_claim_occurrences_extends_short_claim_to_previous_sentence():
    answer = "能力レベルの定義は規格本文に示されている。そうである[^1]。"
    got = iter_claim_occurrences(answer)
    assert "能力レベルの定義は規格本文に示されている" in got[0].claim


def test_iter_claim_occurrences_ignores_markers_inside_code():
    answer = "本文[^1]。\n```\n[^2]\n```\n"
    got = iter_claim_occurrences(answer)
    assert [(c.n, c.answer_occurrence) for c in got] == [(1, 0)]


def test_iter_claim_occurrences_ignores_indented_code_block():
    # markdown-it は4スペース始まりの行も <pre><code> にする。FE と計数を揃えるため
    # BE 側でもマスクしないと answer_occurrence が全域でズレる。
    answer = "本文はここに書かれている[^1]。\n\n    sample = data[^2]\n"
    got = iter_claim_occurrences(answer)
    assert [(c.n, c.answer_occurrence) for c in got] == [(1, 0)]
