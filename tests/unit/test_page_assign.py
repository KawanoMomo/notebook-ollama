"""マーカー→ページ割当の境界(spec §9: 戻り/スキップ/無し/最終/跨り)。"""
from core.recording.page_assign import page_for

MARKERS = [(0, 1), (10_000, 2), (25_000, 5), (40_000, 3)]  # p5へスキップ→p3へ戻り


def test_before_first_marker_is_none():
    assert page_for(500, [(1_000, 1)]) is None


def test_exact_marker_time_belongs_to_that_page():
    assert page_for(10_000, MARKERS) == 2


def test_between_markers_uses_previous():
    assert page_for(24_999, MARKERS) == 2
    assert page_for(26_000, MARKERS) == 5


def test_after_last_marker_uses_last():
    assert page_for(99_999, MARKERS) == 3  # ページ戻り後の最終値


def test_no_markers_or_no_start_ms():
    assert page_for(1234, []) is None
    assert page_for(None, MARKERS) is None
