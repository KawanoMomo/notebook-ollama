"""話者声紋 embedding の抽出・類似度計算・横セッションマッチング。"""

from pathlib import Path

import numpy as np
import soundfile as sf

from core.recording.diarizer import SpeakerSegment


class SpeakerEmbedder:
    """sherpa-onnx SpeakerEmbeddingExtractor ラッパ。

    16kHz mono float32 PCM を入力に、固定次元 (~192) の embedding ベクトルを返す。
    """

    def __init__(self, model_path: Path):
        import sherpa_onnx
        cfg = sherpa_onnx.SpeakerEmbeddingExtractorConfig(
            model=str(model_path),
            num_threads=2,
            provider="cpu",
        )
        self._extractor = sherpa_onnx.SpeakerEmbeddingExtractor(cfg)

    def extract(self, audio: np.ndarray, sample_rate: int = 16000) -> np.ndarray:
        """音声サンプルから embedding を抽出する。

        audio: shape (N,) float32, 16kHz mono.
        戻り値: shape (D,) float32 numpy 配列 (D は通常 192)。
        """
        stream = self._extractor.create_stream()
        stream.accept_waveform(sample_rate=sample_rate, waveform=audio)
        stream.input_finished()
        emb = self._extractor.compute(stream)
        return np.asarray(emb, dtype=np.float32)


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """1-D ベクトル同士の cosine 類似度 ([-1, 1])。"""
    na = float(np.linalg.norm(a))
    nb = float(np.linalg.norm(b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def serialize_embedding(emb: np.ndarray) -> bytes:
    """embedding を SQLite BLOB 用 bytes に変換 (float32 little-endian)。"""
    return np.ascontiguousarray(emb, dtype=np.float32).tobytes()


def deserialize_embedding(blob: bytes) -> np.ndarray:
    """BLOB → numpy float32 1-D ベクトル。"""
    return np.frombuffer(blob, dtype=np.float32)


def best_named_match(
    query: np.ndarray,
    candidates: list[tuple[str, bytes]],
    threshold: float = 0.7,
) -> tuple[str, float] | None:
    """query embedding に最も似ている (name, embedding) を返す。

    candidates: [(display_name, embedding_bytes), ...] 同名複数行 OK。
    threshold 未満なら None。同名複数行のうち最大類似度を採用。
    """
    best_name: str | None = None
    best_sim = -1.0
    for name, blob in candidates:
        emb = deserialize_embedding(blob)
        sim = cosine_similarity(query, emb)
        if sim > best_sim:
            best_sim = sim
            best_name = name
    if best_name is None or best_sim < threshold:
        return None
    return (best_name, best_sim)


def extract_speaker_embeddings(
    wav_path: Path,
    diarization: list[SpeakerSegment],
    embedder: SpeakerEmbedder,
    min_segment_ms: int = 1000,
) -> dict[str, np.ndarray]:
    """各話者の最長セグメントから embedding を抽出して返す。

    短すぎる発話 (< min_segment_ms) しかない話者は結果に含まれない。
    """
    longest: dict[str, SpeakerSegment] = {}
    for seg in diarization:
        cur = longest.get(seg.speaker_id)
        seg_dur = seg.end_ms - seg.start_ms
        cur_dur = (cur.end_ms - cur.start_ms) if cur else 0
        if seg_dur > cur_dur:
            longest[seg.speaker_id] = seg

    if not longest:
        return {}

    audio, sr = sf.read(str(wav_path), dtype="float32")
    if sr != 16000:
        raise ValueError(f"expected 16kHz, got {sr}Hz")
    if audio.ndim > 1:
        audio = audio.mean(axis=1).astype(np.float32)

    out: dict[str, np.ndarray] = {}
    for spk_id, seg in longest.items():
        if (seg.end_ms - seg.start_ms) < min_segment_ms:
            continue
        start_sample = (seg.start_ms * 16000) // 1000
        end_sample = (seg.end_ms * 16000) // 1000
        chunk = audio[start_sample:end_sample]
        if len(chunk) < min_segment_ms * 16:  # 念のため
            continue
        out[spk_id] = embedder.extract(chunk, sample_rate=16000)
    return out
