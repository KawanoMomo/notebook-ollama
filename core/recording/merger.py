from dataclasses import replace

from core.recording.diarizer import SpeakerSegment
from core.recording.transcriber import TranscriptSegment

UNKNOWN_SPEAKER = "spk_unknown"


def merge(
    transcripts: list[TranscriptSegment],
    diarization: list[SpeakerSegment],
) -> list[TranscriptSegment]:
    """transcript セグメントに diarization の speaker_id を割り当てる純粋関数。

    各 transcript について、diarization 区間との overlap (ms) を計算し、
    overlap > 0 のうち最大の speaker を割り当てる。
    タイの場合は diarization リスト先頭の speaker を返す (決定論的)。
    どの diarization 区間とも overlap しない場合は 'spk_unknown'。

    入力は変更しない。戻り値は start_ms 昇順でソート済。

    S2 では single-source (transcripts 1 本) 用。S3 で mic+system 2 ソースの
    マージと「重なり >50% 警告 + 両方残す」(§7.4) が追加される。
    """
    out: list[TranscriptSegment] = []
    for t in transcripts:
        speaker_id = _best_speaker_for_transcript(t, diarization)
        out.append(replace(t, speaker_id=speaker_id))
    out.sort(key=lambda s: s.start_ms)
    return out


def _best_speaker_for_transcript(
    t: TranscriptSegment,
    diar: list[SpeakerSegment],
) -> str:
    best_speaker = UNKNOWN_SPEAKER
    best_overlap = 0
    for d in diar:
        ov = _overlap_ms(t.start_ms, t.end_ms, d.start_ms, d.end_ms)
        if ov > best_overlap:
            best_overlap = ov
            best_speaker = d.speaker_id
    return best_speaker


def _overlap_ms(a_start: int, a_end: int, b_start: int, b_end: int) -> int:
    return max(0, min(a_end, b_end) - max(a_start, b_start))
