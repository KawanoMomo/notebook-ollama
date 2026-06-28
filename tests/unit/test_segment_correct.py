import asyncio
from core.recording.segment_correct import Segment, correct_segments_aligned


def test_empty_input():
    out = asyncio.run(correct_segments_aligned([], _Echo(), "m"))
    assert out == []


def test_preserves_count_timecode_speaker_and_order():
    segs = [Segment(0, 1000, "あなた", "ええーっと これは"),
            Segment(1000, 2000, "相手1", "はい そうですね"),
            Segment(2000, 3000, "あなた", "なるほど")]
    out = asyncio.run(correct_segments_aligned(segs, _Echo(), "m", batch_size=8))
    assert len(out) == 3
    assert [s.start_ms for s in out] == [0, 1000, 2000]
    assert [s.end_ms for s in out] == [1000, 2000, 3000]
    assert [s.speaker for s in out] == ["あなた", "相手1", "あなた"]
    # _Echo returns corrected lines that prefix 整: — text should change but stay aligned
    assert all(s.text.startswith("整:") for s in out)


def test_mismatched_count_keeps_originals():
    segs = [Segment(0, 1000, "あなた", "原文1"), Segment(1000, 2000, "相手1", "原文2")]
    out = asyncio.run(correct_segments_aligned(segs, _BadCount(), "m", batch_size=8))
    assert [s.text for s in out] == ["原文1", "原文2"]  # unchanged on mismatch


def test_llm_error_keeps_originals():
    segs = [Segment(0, 1000, "あなた", "原文1")]
    out = asyncio.run(correct_segments_aligned(segs, _Raises(), "m"))
    assert out[0].text == "原文1"


class _Echo:
    # returns N corrected lines matching the N input lines, prefixed "整:"
    async def generate(self, *, model, prompt, options=None):
        # extract the numbered input lines from the prompt and echo them corrected
        import re
        lines = re.findall(r'^\s*(\d+)\.\s*(.*)$', prompt, re.MULTILINE)
        return "\n".join(f"{n}. 整:{t}" for n, t in lines)


class _BadCount:
    async def generate(self, *, model, prompt, options=None):
        return "1. only one line"  # wrong count for a 2-seg batch


class _Raises:
    async def generate(self, *, model, prompt, options=None):
        raise RuntimeError("llm down")
