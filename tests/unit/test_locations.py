from core.generation.locations import format_location


def test_format_location_page_only():
    assert format_location(page=42, heading_path=None) == "p.42"


def test_format_location_heading_only():
    assert format_location(page=None, heading_path="Ch1 > S1") == "Ch1 > S1"


def test_format_location_both():
    assert format_location(page=42, heading_path="Ch1 > S1") == "p.42, Ch1 > S1"


def test_format_location_neither():
    assert format_location(page=None, heading_path=None) == ""


def test_page_only():
    assert format_location(page=3, heading_path=None) == "p.3"


def test_page_with_tile_is_one_based_for_display():
    # tile_index は 0 始まりで保持し、表示は +1 する
    assert format_location(page=3, heading_path=None, tile_index=0) == "p.3 タイル1"
    assert format_location(page=3, heading_path=None, tile_index=1) == "p.3 タイル2"


def test_tile_comes_before_heading_path():
    assert (
        format_location(page=3, heading_path="第2章 > 2.1", tile_index=1)
        == "p.3 タイル2, 第2章 > 2.1"
    )


def test_tile_ignored_when_page_is_none():
    assert format_location(page=None, heading_path=None, tile_index=1) == ""


def test_audio_location_still_wins_over_tile():
    assert format_location(
        page=3, heading_path=None, start_ms=83000, speaker="相手1", tile_index=1
    ) == "相手1 00:01:23"
