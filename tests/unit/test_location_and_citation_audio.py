from core.generation.citations import CitationSpec, build_citations
from core.generation.locations import format_location, format_timecode


def test_format_timecode():
    assert format_timecode(754_000) == "00:12:34"   # 754 s = 12 min 34 s
    assert format_timecode(3_661_000) == "01:01:01"  # 3661 s = 1 h 1 m 1 s
    assert format_timecode(-5) == "00:00:00"


def test_format_location_recording():
    result = format_location(page=None, heading_path=None, start_ms=754_000, speaker="相手1")
    assert result == "相手1 00:12:34"


def test_format_location_speaker_only_and_time_only():
    assert format_location(page=None, heading_path=None, speaker="あなた") == "あなた"
    assert format_location(page=None, heading_path=None, start_ms=0) == "00:00:00"


def test_format_location_document_unchanged():
    assert format_location(page=8, heading_path="第1章") == "p.8, 第1章"


def test_build_citations_includes_audio_ref():
    specs = {1: CitationSpec(chunk_id="c1", source_id="src", source_title="録音1",
                             location="相手1 00:12:34", url_or_path=None, snippet="...",
                             audio_source_id="src", audio_start_ms=754_000, audio_channel="system")}
    out = build_citations(answer="ans [^1]", specs=specs)
    assert out[0]["audio_source_id"] == "src"
    assert out[0]["audio_start_ms"] == 754_000
    assert out[0]["audio_channel"] == "system"


def test_build_citations_document_audio_refs_none():
    specs = {1: CitationSpec(chunk_id="c1", source_id="src", source_title="doc",
                             location="p.8", url_or_path=None, snippet="...")}
    out = build_citations(answer="ans [^1]", specs=specs)
    assert out[0]["audio_source_id"] is None
    assert out[0]["audio_start_ms"] is None
    assert out[0]["audio_channel"] is None
