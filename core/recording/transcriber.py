from __future__ import annotations

import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

# --- vendored from meeting-transcriber (app._cuda_dll) ---
# Upstream registered CUDA (cuBLAS/cuDNN) DLL search paths at `app` package
# import time, *before* importing WhisperModel. The implementation lives in
# `core.accel.cuda_dll` so `core.accel.probe.probe_cuda()` can call it
# without pulling faster_whisper into the probe path (see plan Sprint 1 /
# Task 1.1). Re-exported here for backward compatibility with existing
# callers / tests that import `_register_cuda_dll_dirs` from this module.
from core.accel.cuda_dll import _register_cuda_dll_dirs

# --- whisper postprocess (Sprint 3 / Task 3.1) ---
# RMS floor, hallucination blocklist, confidence mapping were extracted into
# core.recording.whisper_postprocess so they can be unit-tested without
# loading faster-whisper / CUDA. ``apply_rms_floor``, ``_logprob_to_confidence``,
# and ``_is_hallucination_phrase`` are used directly below; the remaining
# names are re-exported under their original ``_``-prefixed identifiers so
# existing ``from core.recording.transcriber import _is_hallucination_phrase``
# style call sites continue to work without modification.
from core.recording.whisper_postprocess import (
    HALLUCINATION_NORM as _HALLUCINATION_NORM,  # noqa: F401  -- re-export
)
from core.recording.whisper_postprocess import (
    HALLUCINATION_SILENCE_RMS as _HALLUCINATION_SILENCE_RMS,  # noqa: F401  -- re-export
)
from core.recording.whisper_postprocess import (
    apply_rms_floor,
    is_voice,  # noqa: F401  -- re-export for live_caption / future backends
)
from core.recording.whisper_postprocess import (
    logprob_to_confidence as _logprob_to_confidence,
)
from core.recording.whisper_postprocess import (
    normalize_for_hallucination_check as _normalize_caption,  # noqa: F401  -- re-export
)
from core.recording.whisper_postprocess import (
    should_filter_hallucination as _is_hallucination_phrase,
)

if TYPE_CHECKING:
    import numpy as np


# --- vendored from meeting-transcriber (app.models.schema.TranscriptSegment) ---
# The upstream module imported `from app.models.schema import TranscriptSegment`.
# 10_NotebookOllama has no `app` package, so the single dataclass actually used
# by this module is inlined verbatim (see PROVENANCE.md "Local divergences").
@dataclass
class TranscriptSegment:
    id: int | None
    session_id: str
    channel: str              # 'mic' | 'system'
    start_ms: int
    end_ms: int
    speaker_id: str
    text: str
    language: str | None = None
    confidence: float | None = None
    edited: bool = False
    original_text: str | None = None


# モジュール import 時に一度だけ登録 (WhisperModel import 前)。
_CUDA_DLL_REGISTERED = _register_cuda_dll_dirs()

# テスト互換用センチネル (テスト fake で参照される空オブジェクト)
FAKE_RESULT = object()

_GPU_ERROR_HINTS = ("cublas", "cudnn", "cuda", "gpu")


def _is_gpu_runtime_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(h in msg for h in _GPU_ERROR_HINTS)


class Transcriber:
    # _lock 生成を保護する class-level lock (テストが __new__ で __init__ を
    # バイパスするケースでも _lock を遅延生成できるようにする)。
    _lock_init_guard = threading.Lock()

    def __init__(
        self,
        model_size: str = "large-v3",
        device: str = "cuda",
        compute_type: str = "float16",
    ):
        from faster_whisper import WhisperModel
        self._model_size = model_size
        self._device = device
        self._compute_type = compute_type
        self._model = WhisperModel(model_size, device=device, compute_type=compute_type)
        self.fell_back_to_cpu = False
        # mic/system 用の 2 つの LiveCaption スレッドが同一 Transcriber を共有するため、
        # transcribe 呼び出し + 遅延ジェネレータの反復 + CPU フォールバック (self._model
        # の差し替え) を直列化する。faster-whisper / CTranslate2 は concurrent 呼び出しの
        # thread-safety を保証していない。
        self._lock = threading.Lock()

    @property
    def effective_device(self) -> str:
        """実際に推論に使われているデバイス ('cuda' / 'cpu')。
        CUDA 初期化失敗で CPU フォールバックした場合は 'cpu' を返す。"""
        return self._device

    @property
    def _serial_lock(self) -> threading.Lock:
        """推論直列化用ロック。__init__ をバイパスした (テスト等) 場合も遅延生成する。"""
        lk = self.__dict__.get("_lock")
        if lk is None:
            with Transcriber._lock_init_guard:
                lk = self.__dict__.get("_lock")
                if lk is None:
                    lk = threading.Lock()
                    self._lock = lk
        return lk

    def _fallback_to_cpu(self, reason: Exception) -> None:
        from faster_whisper import WhisperModel
        print(
            f"[transcriber] GPU runtime failed ({type(reason).__name__}: {reason}); "
            f"falling back to CPU/int8 (model={self._model_size})",
            file=sys.stderr, flush=True,
        )
        self._model = WhisperModel(self._model_size, device="cpu", compute_type="int8")
        self._device = "cpu"
        self._compute_type = "int8"
        self.fell_back_to_cpu = True

    def transcribe(
        self,
        wav_path: Path,
        *,
        channel: str,
        speaker_id: str,
        language: str | None = "ja",
        session_id: str = "",
    ) -> list[TranscriptSegment]:
        # 遅延ジェネレータの反復まで含めてロックで直列化する
        # (transcribe() は呼び出し時点では推論せず、反復時に self._model を使うため)。
        with self._serial_lock:
            try:
                segments_iter, info = self._model.transcribe(
                    str(wav_path), language=language, beam_size=5, vad_filter=True,
                )
                return self._collect(segments_iter, info, channel, speaker_id, session_id)
            except RuntimeError as e:
                if self._device != "cuda" or not _is_gpu_runtime_error(e):
                    raise
                self._fallback_to_cpu(e)
                segments_iter, info = self._model.transcribe(
                    str(wav_path), language=language, beam_size=5, vad_filter=True,
                )
                return self._collect(segments_iter, info, channel, speaker_id, session_id)

    def _collect(
        self, segments_iter, info, channel: str, speaker_id: str, session_id: str,
    ) -> list[TranscriptSegment]:
        out: list[TranscriptSegment] = []
        for seg in segments_iter:
            text = seg.text.strip()
            # 空セグメント / 定型ハルシネーション (「ご視聴ありがとうございました」等) を除外
            if not text or _is_hallucination_phrase(text):
                continue
            out.append(TranscriptSegment(
                id=None,
                session_id=session_id,
                channel=channel,
                start_ms=int(seg.start * 1000),
                end_ms=int(seg.end * 1000),
                speaker_id=speaker_id,
                text=text,
                language=info.language,
                confidence=_logprob_to_confidence(seg.avg_logprob),
            ))
        return out


    def transcribe_array(
        self,
        audio: np.ndarray,        # float32 [-1, 1] mono
        sample_rate: int = 16000,
        language: str | None = "ja",
        base_ms: int = 0,
    ) -> list[dict]:
        """numpy 配列から直接 transcribe する (ライブ字幕用)。

        戻り値は dict 列で TranscriptSegment 構造のサブセット:
        [{start_ms, end_ms, text, language, confidence}]
        base_ms はチャンクの絶対オフセット (live caption 用)。
        """
        import numpy as np

        if sample_rate != 16000:
            # faster-whisper は 16kHz 想定。再サンプルは呼び出し側責任。
            pass

        # 無音/極低レベルはモデルに渡さない (Whisper のハルシネーション源を断つ)。
        # apply_rms_floor は silence なら [] を返す (early-return signal)、
        # 非 silent なら None を返して下のモデル呼び出しに進ませる。
        audio = audio.astype(np.float32)
        early = apply_rms_floor(audio)
        if early is not None:
            return early

        # ライブ字幕でのハルシネーション抑制:
        #  - vad_filter=True で無音区間を除外
        #  - condition_on_previous_text=False で「ご視聴ありがとうございました」等の
        #    定型句が前チャンクの出力に条件付けされて繰り返されるのを防ぐ (再発の主因)
        _kw = dict(
            language=language, beam_size=1, vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 500},
            condition_on_previous_text=False,
            no_speech_threshold=0.6,
        )
        # mic/system 2 スレッドからの同時呼び出しを直列化 (遅延反復まで保持)。
        with self._serial_lock:
            try:
                segments_iter, info = self._model.transcribe(audio, **_kw)
            except RuntimeError as e:
                if self._device == "cuda" and _is_gpu_runtime_error(e):
                    self._fallback_to_cpu(e)
                    segments_iter, info = self._model.transcribe(audio, **_kw)
                else:
                    raise

            out: list[dict] = []
            for seg in segments_iter:
                # 明白な非発話セグメント / 定型ハルシネーションを除外。
                # 閾値は高め(0.85)にして実発話(通常 nsp≪0.6)の誤除去を避ける。
                if getattr(seg, "no_speech_prob", 0.0) > 0.85:
                    continue
                text = seg.text.strip()
                if not text or _is_hallucination_phrase(text):
                    continue
                out.append({
                    "start_ms": int(seg.start * 1000) + base_ms,
                    "end_ms": int(seg.end * 1000) + base_ms,
                    "text": text,
                    "language": info.language,
                    "confidence": _logprob_to_confidence(seg.avg_logprob),
                })
            return out


# NOTE: `_logprob_to_confidence`, `_HALLUCINATION_SILENCE_RMS`,
# `_normalize_caption`, `_HALLUCINATION_NORM`, `_is_hallucination_phrase`,
# `apply_rms_floor`, and `is_voice` now live in
# `core.recording.whisper_postprocess` (Sprint 3 / Task 3.1). They are
# re-exported at the top of this module under their original names so older
# `from core.recording.transcriber import _is_hallucination_phrase` style
# call sites continue to work without modification.
