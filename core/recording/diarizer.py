from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

import numpy as np
import soundfile as sf


# --- vendored from meeting-transcriber (app.models.schema.SpeakerSegment) ---
# The upstream module imported `from app.models.schema import SpeakerSegment` and
# re-exported it (embeddings.py imports SpeakerSegment from this module).
# 10_NotebookOllama has no `app` package, so the single dataclass actually used
# is inlined verbatim here, keeping diarizer.py the canonical SpeakerSegment home
# (see PROVENANCE.md "Local divergences").
@dataclass
class SpeakerSegment:
    """diarization の出力。話者分離器が返すタイムスライス。"""
    speaker_id: str
    start_ms: int
    end_ms: int


@runtime_checkable
class Diarizer(Protocol):
    """話者分離器の抽象IF。

    実装は Task 3 (SherpaDiarizer)。S5 で embedding 出力対応に拡張される。
    """

    def diarize(self, wav_path: Path) -> list[SpeakerSegment]:
        """音声ファイルを話者ごとのタイムセグメントに分割する。

        speaker_id は 'spk_001', 'spk_002', ... のように
        セッション内連番で一意。順序: start_ms 昇順を推奨。
        """
        ...


class SherpaDiarizer:
    """sherpa-onnx OfflineSpeakerDiarization ラッパ。"""

    def __init__(
        self,
        segmentation_model: Path,
        embedding_model: Path,
        threshold: float = 0.5,
        num_clusters: int = -1,
        min_duration_on: float = 0.3,
        min_duration_off: float = 0.5,
    ):
        import sherpa_onnx

        cfg = sherpa_onnx.OfflineSpeakerDiarizationConfig(
            segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
                pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(
                    model=str(segmentation_model),
                ),
            ),
            embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(
                model=str(embedding_model),
            ),
            clustering=sherpa_onnx.FastClusteringConfig(
                num_clusters=num_clusters,
                threshold=threshold,
            ),
            min_duration_on=min_duration_on,
            min_duration_off=min_duration_off,
        )
        self._impl = sherpa_onnx.OfflineSpeakerDiarization(cfg)

    def diarize(self, wav_path: Path) -> list[SpeakerSegment]:
        audio, sr = sf.read(str(wav_path), dtype="float32")
        if sr != self._impl.sample_rate:
            raise ValueError(
                f"expected {self._impl.sample_rate}Hz (16kHz) audio, got {sr}Hz"
            )
        if audio.ndim > 1:
            audio = audio.mean(axis=1).astype(np.float32)

        segments = self._impl.process(audio).sort_by_start_time()
        return _convert_sherpa_segments(segments)


def _convert_sherpa_segments(segments) -> list[SpeakerSegment]:
    """sherpa-onnx SpeakerSegmentInfo 列を SpeakerSegment 列に変換する。"""
    return [
        SpeakerSegment(
            speaker_id=f"spk_{int(s.speaker):03d}",
            start_ms=int(round(s.start * 1000)),
            end_ms=int(round(s.end * 1000)),
        )
        for s in segments
    ]
