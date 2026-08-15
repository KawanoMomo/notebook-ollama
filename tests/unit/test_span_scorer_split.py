from core.retrieval.span_scorer import split_sentences


def test_splits_japanese_by_kuten():
    got = split_sentences("これは一文目である。これは二文目である。")
    assert [s.text for s in got] == ["これは一文目である。", "これは二文目である。"]


def test_offsets_point_into_original():
    src = "これは一文目である。これは二文目である。"
    for s in split_sentences(src):
        assert src[s.start : s.end] == s.text


def test_does_not_oversplit_english_abbreviations():
    got = split_sentences("See Fig. 3 for details. The next sentence follows here.")
    assert len(got) == 2
    assert got[0].text.startswith("See Fig. 3")


def test_table_markdown_row_is_one_unit():
    got = split_sentences("| 項目 | 値 |\n| --- | --- |\n| A | 1 |")
    assert len(got) == 3


def test_short_fragment_merges_forward():
    got = split_sentences("うん。とても長い説明がここに続いていて十分な長さがある。")
    assert len(got) == 1
