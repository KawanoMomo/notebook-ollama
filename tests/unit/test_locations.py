from core.generation.locations import format_location

def test_format_location_page_only():
    assert format_location(page=42, heading_path=None) == "p.42"

def test_format_location_heading_only():
    assert format_location(page=None, heading_path="Ch1 > S1") == "Ch1 > S1"

def test_format_location_both():
    assert format_location(page=42, heading_path="Ch1 > S1") == "p.42, Ch1 > S1"

def test_format_location_neither():
    assert format_location(page=None, heading_path=None) == ""
