"""ミュート区間によるオフラインセグメント除外ヘルパの単体テスト(純粋ロジック)。

時間基準の注意:
  - ミュート区間 ms は t0(録音開始)相対。
  - STT セグメント ms は WAV 先頭相対。
  - 比較前に各区間から ``wav_start_offset_ms`` を **減算** して WAV 相対へ変換する。
  - オフセットは近似(~64ms バッファ + ジッタ)なので、境界は **保守的**:
    セグメントとミュート区間が少しでも重なれば(端の接触も含め)除外する。
"""

import json

from core.recording.mute_filter import (
    filter_muted_segments,
    load_mute_intervals,
    segment_is_muted,
    to_wav_relative,
)
from core.recording.segment_correct import Segment


# --- load_mute_intervals ---------------------------------------------------


def test_load_mute_intervals_missing_file_returns_zero_structure(tmp_path):
    """mute_intervals.json が無い(古い録音)→ 除外ゼロの空構造。"""
    loaded = load_mute_intervals(tmp_path)
    assert loaded == {"wav_start_offset_ms": 0, "mic": [], "system": []}


def test_load_mute_intervals_reads_existing(tmp_path):
    (tmp_path / "mute_intervals.json").write_text(
        json.dumps(
            {
                "version": 1,
                "wav_start_offset_ms": 137,
                "mic": [{"start_ms": 70000, "end_ms": 95000}],
                "system": [],
            }
        ),
        encoding="utf-8",
    )
    loaded = load_mute_intervals(tmp_path)
    assert loaded["wav_start_offset_ms"] == 137
    assert loaded["mic"] == [{"start_ms": 70000, "end_ms": 95000}]
    assert loaded["system"] == []


def test_load_mute_intervals_missing_keys_default_safely(tmp_path):
    (tmp_path / "mute_intervals.json").write_text(
        json.dumps({"version": 1}), encoding="utf-8"
    )
    loaded = load_mute_intervals(tmp_path)
    assert loaded == {"wav_start_offset_ms": 0, "mic": [], "system": []}


def test_load_mute_intervals_corrupt_json_returns_zero_structure(tmp_path):
    (tmp_path / "mute_intervals.json").write_text("not json{", encoding="utf-8")
    loaded = load_mute_intervals(tmp_path)
    assert loaded == {"wav_start_offset_ms": 0, "mic": [], "system": []}


# --- to_wav_relative -------------------------------------------------------


def test_to_wav_relative_subtracts_offset():
    intervals = [{"start_ms": 70000, "end_ms": 95000}]
    assert to_wav_relative(intervals, 137) == [(69863, 94863)]


def test_to_wav_relative_clamps_start_at_zero():
    # start - offset が負になっても 0 でクランプ(end は減算後そのまま)
    intervals = [{"start_ms": 50, "end_ms": 1000}]
    assert to_wav_relative(intervals, 200) == [(0, 800)]


def test_to_wav_relative_zero_offset_identity():
    intervals = [{"start_ms": 1000, "end_ms": 2000}]
    assert to_wav_relative(intervals, 0) == [(1000, 2000)]


def test_to_wav_relative_empty():
    assert to_wav_relative([], 137) == []


# --- segment_is_muted (保守的: 重なれば True) -------------------------------


def test_segment_fully_inside_muted_is_muted():
    assert segment_is_muted(72000, 73000, [(69863, 94863)]) is True


def test_segment_fully_outside_is_not_muted():
    assert segment_is_muted(0, 1000, [(69863, 94863)]) is False
    assert segment_is_muted(100000, 101000, [(69863, 94863)]) is False


def test_segment_partial_overlap_at_start_is_muted():
    # セグメントがミュート区間の頭に食い込む -> 保守的に除外
    assert segment_is_muted(69000, 70000, [(69863, 94863)]) is True


def test_segment_partial_overlap_at_end_is_muted():
    assert segment_is_muted(94000, 96000, [(69863, 94863)]) is True


def test_segment_boundary_touch_is_muted_inclusive():
    # 端の接触(end == muted.start)も保守的に除外(inclusive)
    assert segment_is_muted(60000, 69863, [(69863, 94863)]) is True
    assert segment_is_muted(94863, 96000, [(69863, 94863)]) is True


def test_segment_muting_spans_segment():
    # ミュート区間がセグメントを完全に内包
    assert segment_is_muted(70000, 72000, [(69000, 95000)]) is True


def test_segment_with_no_intervals_is_not_muted():
    assert segment_is_muted(1000, 2000, []) is False


def test_segment_overlaps_any_of_multiple_intervals():
    intervals = [(0, 1000), (5000, 6000), (9000, 10000)]
    assert segment_is_muted(5500, 5800, intervals) is True
    assert segment_is_muted(2000, 3000, intervals) is False


def test_segment_with_missing_ms_is_not_muted():
    # タイムスタンプ欠落セグメントは安全側: 落とさない
    assert segment_is_muted(None, 2000, [(0, 100000)]) is False
    assert segment_is_muted(1000, None, [(0, 100000)]) is False
    assert segment_is_muted(None, None, [(0, 100000)]) is False


# --- filter_muted_segments -------------------------------------------------


def _seg(start, end, speaker="あなた", text="x"):
    return Segment(start_ms=start, end_ms=end, speaker=speaker, text=text)


def test_filter_drops_overlapping_keeps_rest():
    segs = [
        _seg(0, 1000),       # outside -> keep
        _seg(70000, 71000),  # inside muted -> drop
        _seg(94000, 96000),  # partial overlap at end -> drop
        _seg(100000, 101000),  # outside -> keep
    ]
    # t0-relative interval 70000-95000, offset 0
    intervals = [{"start_ms": 70000, "end_ms": 95000}]
    kept, dropped = filter_muted_segments(segs, intervals, offset_ms=0)
    assert dropped == 2
    assert [(s.start_ms, s.end_ms) for s in kept] == [(0, 1000), (100000, 101000)]


def test_filter_applies_offset_subtraction():
    # offset 5000: t0-relative 70000-95000 -> WAV 65000-90000
    segs = [
        _seg(64000, 64500),  # before WAV-relative window -> keep
        _seg(66000, 67000),  # inside WAV-relative window -> drop
    ]
    intervals = [{"start_ms": 70000, "end_ms": 95000}]
    kept, dropped = filter_muted_segments(segs, intervals, offset_ms=5000)
    assert dropped == 1
    assert [(s.start_ms, s.end_ms) for s in kept] == [(64000, 64500)]


def test_filter_no_intervals_keeps_all():
    segs = [_seg(0, 1000), _seg(2000, 3000)]
    kept, dropped = filter_muted_segments(segs, [], offset_ms=0)
    assert dropped == 0
    assert kept == segs


def test_filter_empty_segments():
    kept, dropped = filter_muted_segments([], [{"start_ms": 0, "end_ms": 100}], 0)
    assert kept == []
    assert dropped == 0


def test_filter_keeps_segment_without_ms():
    segs = [Segment(start_ms=None, end_ms=None, speaker="あなた", text="x")]
    intervals = [{"start_ms": 0, "end_ms": 100000}]
    kept, dropped = filter_muted_segments(segs, intervals, offset_ms=0)
    assert dropped == 0
    assert kept == segs
