from core.generation.evidence_spans import cjk_ratio, normalize_for_match


def test_normalize_keeps_reverse_index_map():
    src = "ABC DEF"
    got = normalize_for_match(src)
    assert len(got.text) == len(got.origin)
    # 先頭文字は元の位置 0 に対応する
    assert got.origin[0] == 0
    # 末尾文字は元の末尾に対応する
    assert got.origin[-1] == len(src) - 1


def test_normalize_drops_space_between_cjk():
    got = normalize_for_match("レベル 2 では")
    assert got.text == "レベル2では"


def test_normalize_collapses_space_between_latin():
    got = normalize_for_match("process   capability  level")
    assert got.text == "process capability level"


def test_normalize_folds_width_and_case():
    got = normalize_for_match("ＡＢＣ Ｄ")
    assert got.text.startswith("abc")


def test_normalize_drops_punctuation():
    got = normalize_for_match("レベル1は、成果(達成)を示す。")
    assert "、" not in got.text
    assert "(" not in got.text


def test_cjk_ratio():
    assert cjk_ratio("レベル1は成果") > 0.3
    assert cjk_ratio("process capability level 1") < 0.3
