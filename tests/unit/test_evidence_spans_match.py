from core.generation.evidence_spans import resolve_lexical_span

CHUNK = (
    "プロセス能力レベル1は、実施されたプロセスの成果が達成されていることを示す。"
    "レベル2では作業成果物が適切に管理される。"
    "監視及び調整、責任と権限の定義、資源の特定と利用可能化が求められる。"
)


def test_exact_match_returns_span():
    span = resolve_lexical_span("レベル2では作業成果物が適切に管理される", CHUNK)
    assert span is not None
    start, end = span
    assert CHUNK[start:end].startswith("レベル2では作業成果物")


def test_second_claim_maps_to_different_span():
    first = resolve_lexical_span("プロセス能力レベル1は実施されたプロセスの成果が達成されている", CHUNK)
    second = resolve_lexical_span("監視及び調整、責任と権限の定義、資源の特定が求められる", CHUNK)
    assert first is not None and second is not None
    assert first[0] < second[0]


def test_paraphrase_returns_none():
    assert resolve_lexical_span("段階が上がると管理の度合いが増していく仕組みである", CHUNK) is None


def test_cross_language_returns_none():
    english = "Process capability level 1 indicates that the process achieves its outcomes."
    assert resolve_lexical_span("レベル1は成果の達成を示している", english) is None


def test_english_false_positive_is_rejected():
    chunk = (
        "The system shall provide a process for configuration management. "
        "Each process must define its own measurement framework."
    )
    # 頻出語 process / system のみを共有する非根拠文は採用しない
    assert resolve_lexical_span("The process of the system is fine.", chunk) is None


def test_english_true_match_is_accepted():
    chunk = (
        "The system shall provide a process for configuration management. "
        "Each process must define its own measurement framework."
    )
    span = resolve_lexical_span("Each process must define its own measurement framework", chunk)
    assert span is not None
    assert "measurement framework" in chunk[span[0] : span[1]]
