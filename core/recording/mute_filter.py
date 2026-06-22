"""オフライン変換でのミュート区間セグメント除外(純粋ロジック)。

2-BE1 が録音停止時に書く ``mute_intervals.json`` を読み、各チャンネルの STT 結果
セグメントのうち、該当チャンネルのミュート区間と重なるものを破棄する。除外は
整文(``correct_segments_aligned``)・話者分離・チャンク化・埋め込みより **前** に
行うため、ミュート区間の内容は LLM 推論にも埋め込みにも一切到達しない(設計 §2.5)。

時間基準の注意(設計 §6 / 2-BE1 の write_mute_intervals docstring):
  - ミュート区間 ms は t0(録音開始)相対。
  - STT セグメント ms は WAV 先頭相対。
  - 比較前に各区間から ``wav_start_offset_ms`` を **減算** して WAV 相対へ変換する。
  - オフセットは近似(~64ms バッファ + ジッタ)なので境界は **保守的**:
    セグメントとミュート区間が少しでも重なれば(端の接触も含め)除外する。

WASAPI / whisper / FastAPI に一切依存しない純粋ロジックなので単体テスト可能。
mute_intervals.json が無い古い録音は、空構造を返して何も除外しない(後方互換)。
"""

from __future__ import annotations

import json
from pathlib import Path

from core.logging import get_logger
from core.recording.mute_state import CHANNELS
from core.recording.segment_correct import Segment

log = get_logger("recording.mute_filter")

_ZERO_STRUCTURE: dict = {"wav_start_offset_ms": 0, "mic": [], "system": []}


def load_mute_intervals(recording_dir: Path | str) -> dict:
    """``recording_dir/mute_intervals.json`` を読み、正規化した dict を返す。

    返り値: ``{"wav_start_offset_ms": int, "mic": [...], "system": [...]}``

    - ファイルが無い(古い録音)→ 全ゼロ/空構造(=除外なし)。
    - JSON 破損 / 形状不正 → 同じく空構造(クラッシュさせない)。
    - 欠落キーは安全側のデフォルト(offset=0、区間は空リスト)で補う。
    """
    path = Path(recording_dir) / "mute_intervals.json"
    if not path.exists():
        return {"wav_start_offset_ms": 0, "mic": [], "system": []}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        log.warning("mute_intervals_load_failed", path=str(path))
        return {"wav_start_offset_ms": 0, "mic": [], "system": []}
    if not isinstance(raw, dict):
        return {"wav_start_offset_ms": 0, "mic": [], "system": []}

    def _ms(v) -> int:
        try:
            return int(v)
        except (TypeError, ValueError):
            return 0

    def _intervals(v) -> list[dict]:
        if not isinstance(v, list):
            return []
        return [iv for iv in v if isinstance(iv, dict)]

    return {
        "wav_start_offset_ms": _ms(raw.get("wav_start_offset_ms", 0)),
        **{ch: _intervals(raw.get(ch, [])) for ch in CHANNELS},
    }


def to_wav_relative(
    intervals: list[dict], offset_ms: int
) -> list[tuple[int, int]]:
    """t0 相対のミュート区間群を WAV 先頭相対の (start, end) タプル列に変換する。

    各区間 ms から ``offset_ms`` を減算し、start は 0 でクランプする(end はそのまま;
    end<0 になるような過去の区間は重なり判定で自然に脱落する)。形状不正な区間は無視。
    """
    out: list[tuple[int, int]] = []
    for iv in intervals:
        start = iv.get("start_ms")
        end = iv.get("end_ms")
        if start is None or end is None:
            continue
        try:
            s = int(start) - int(offset_ms)
            e = int(end) - int(offset_ms)
        except (TypeError, ValueError):
            continue
        if s < 0:
            s = 0
        out.append((s, e))
    return out


def segment_is_muted(
    seg_start_ms: int | None,
    seg_end_ms: int | None,
    muted_intervals_wav_relative: list[tuple[int, int]],
) -> bool:
    """セグメントが ANY のミュート区間(WAV 相対)と重なれば True(保守的)。

    - 重なり判定は **inclusive**: 端の接触(``seg_end == muted_start`` など)も重なり
      とみなして除外する(設計 §6 の取りこぼし防止)。
    - タイムスタンプ欠落(start/end が None)のセグメントは安全側で **落とさない**
      (False を返す)。
    """
    if seg_start_ms is None or seg_end_ms is None:
        return False
    for m_start, m_end in muted_intervals_wav_relative:
        # inclusive overlap: seg_start <= m_end かつ seg_end >= m_start
        if seg_start_ms <= m_end and seg_end_ms >= m_start:
            return True
    return False


def filter_muted_segments(
    segments: list[Segment],
    channel_intervals: list[dict],
    offset_ms: int,
) -> tuple[list[Segment], int]:
    """1 チャンネル分のセグメントから、ミュート区間と重なるものを除外する。

    ``channel_intervals`` は t0 相対の ``[{"start_ms","end_ms"}, ...]``(該当チャンネル
    の区間のみ)。``offset_ms`` を減算して WAV 相対に変換してから保守的に重なり判定する。

    返り値: ``(kept_segments, dropped_count)``。区間が空なら入力をそのまま返す。
    """
    if not channel_intervals:
        return list(segments), 0
    wav_rel = to_wav_relative(channel_intervals, offset_ms)
    if not wav_rel:
        return list(segments), 0
    kept: list[Segment] = []
    dropped = 0
    for seg in segments:
        if segment_is_muted(seg.start_ms, seg.end_ms, wav_rel):
            dropped += 1
        else:
            kept.append(seg)
    return kept, dropped
