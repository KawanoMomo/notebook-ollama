import math
import os
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


# --- vendored from meeting-transcriber (app.models.schema.TranscriptSegment) ---
# The upstream module imported `from app.models.schema import TranscriptSegment`.
# 10_NotebookOllama has no `app` package, so the single dataclass actually used
# by this module is inlined verbatim (see PROVENANCE.md "Local divergences").
@dataclass
class TranscriptSegment:
    id: Optional[int]
    session_id: str
    channel: str              # 'mic' | 'system'
    start_ms: int
    end_ms: int
    speaker_id: str
    text: str
    language: Optional[str] = None
    confidence: Optional[float] = None
    edited: bool = False
    original_text: Optional[str] = None


# --- vendored from meeting-transcriber (app._cuda_dll) ---
# Upstream registered CUDA (cuBLAS/cuDNN) DLL search paths at `app` package import
# time, *before* importing WhisperModel. There is no `app` package here, so the
# stdlib-only registration is inlined and run at module import (see PROVENANCE.md).
def _register_cuda_dll_dirs() -> list:
    """nvidia の CUDA DLL を DLL 検索パスへ登録 (win32 のみ、無害な no-op fallback)。"""
    if sys.platform != "win32" or not hasattr(os, "add_dll_directory"):
        return []
    try:
        import importlib.util
        spec = importlib.util.find_spec("nvidia")
    except Exception:
        return []
    if spec is None or not spec.submodule_search_locations:
        return []
    base = list(spec.submodule_search_locations)[0]  # .../site-packages/nvidia
    added = []
    for sub in ("cublas", "cudnn", "cuda_runtime", "cuda_nvrtc"):
        d = os.path.join(base, sub, "bin")
        if os.path.isdir(d):
            try:
                os.add_dll_directory(d)
                added.append(d)
            except OSError:
                pass
    if added:
        # add_dll_directory alone is insufficient on this CUDA stack — ctranslate2
        # cannot resolve cublas64_12.dll's dependencies without PATH. Mirror what
        # meeting-transcriber's start-gpu.bat does, but in-process so a plain
        # `uvicorn` launch gets GPU too.
        os.environ["PATH"] = os.pathsep.join(added) + os.pathsep + os.environ.get("PATH", "")
    return added


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
        language: Optional[str] = "ja",
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
        audio: "np.ndarray",      # float32 [-1, 1] mono
        sample_rate: int = 16000,
        language: Optional[str] = "ja",
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
        audio = audio.astype(np.float32)
        if audio.size == 0 or float(np.sqrt(np.mean(np.square(audio)))) < _HALLUCINATION_SILENCE_RMS:
            return []

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


def _logprob_to_confidence(avg_logprob: float) -> float:
    """avg_logprob (-∞..0) を 0..1 の confidence に正規化する近似。"""
    return max(0.0, min(1.0, math.exp(avg_logprob)))


# これ未満の RMS は無音とみなし STT に渡さない (float32 [-1,1] 基準, ≈ -46 dBFS)。
# 実発話は概ね RMS > 0.05 のため誤除外しない。
_HALLUCINATION_SILENCE_RMS = 0.005


def _normalize_caption(text: str) -> str:
    return text.strip().strip("。.!！?？、,， 　　")


# Whisper が無音/低レベル音声で生成しがちな定型ハルシネーション (YouTube 由来)。
# セグメント全体がこれらに一致するときのみ除外する (実発話の部分文字列は除外しない)。
# 注: 「ご清聴ありがとうございました」は実会議の締めで出るため意図的に含めない。
_HALLUCINATION_NORM = frozenset(_normalize_caption(p) for p in (
    "ご視聴ありがとうございました",
    "ご視聴ありがとうございます",
    "ご視聴いただきありがとうございました",
    "最後までご視聴いただきありがとうございました",
    "チャンネル登録お願いします",
    "チャンネル登録をお願いします",
    "チャンネル登録よろしくお願いします",
))


def _is_hallucination_phrase(text: str) -> bool:
    """セグメント全体が既知の定型ハルシネーションと一致するか。"""
    return _normalize_caption(text) in _HALLUCINATION_NORM
