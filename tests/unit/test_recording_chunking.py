from core.recording.chunking import chunk_segments
from core.recording.segment_correct import Segment


def _wc(s):
    return max(1, len(s.split()))


def test_empty():
    assert chunk_segments([], max_tokens=100, token_counter=_wc) == []


def test_groups_same_speaker_and_splits_on_change():
    segs = [Segment(0, 1000, "あなた", "a b"),
            Segment(1000, 2000, "あなた", "c d"),
            Segment(2000, 3000, "相手1", "e f")]
    chunks = chunk_segments(segs, max_tokens=100, token_counter=_wc)
    assert len(chunks) == 2
    assert chunks[0].speaker == "あなた"
    assert chunks[0].start_ms == 0 and chunks[0].end_ms == 2000
    assert chunks[0].ord == 0
    assert chunks[1].speaker == "相手1"
    assert chunks[1].ord == 1
    assert chunks[1].start_ms == 2000 and chunks[1].end_ms == 3000


def test_splits_when_token_budget_exceeded_same_speaker():
    segs = [Segment(i * 1000, (i + 1) * 1000, "あなた", "w " * 60) for i in range(3)]
    chunks = chunk_segments(segs, max_tokens=100, token_counter=_wc)
    assert len(chunks) >= 2
    assert all(c.speaker == "あなた" for c in chunks)
    # ord values are contiguous 0..n-1
    assert [c.ord for c in chunks] == list(range(len(chunks)))
    # time spans are non-overlapping and ascending
    assert all(chunks[i].end_ms <= chunks[i + 1].start_ms for i in range(len(chunks) - 1))


def test_single_segment():
    chunks = chunk_segments(
        [Segment(500, 1500, "相手1", "hello")], max_tokens=100, token_counter=_wc
    )
    assert len(chunks) == 1
    assert chunks[0].start_ms == 500 and chunks[0].end_ms == 1500 and chunks[0].speaker == "相手1"
