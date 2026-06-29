"""Whisper postprocess helpers extracted from :mod:`core.recording.transcriber`.

Sprint 3 / Task 3.1 of the iGPU/NPU acceleration plan extracts the small,
pure helpers that transform / filter Whisper output before it becomes a
:class:`TranscriptSegment`. Reasons for the split:

* **Testability** — these helpers had been embedded inside ``transcriber.py``
  next to a faster-whisper / CTranslate2 import, making them impossible to
  unit-test on a CUDA-less box. The new module imports ``numpy`` only at
  runtime so the test suite can exercise the filter / VAD / confidence
  mapping without a GPU.
* **Backend pluggability** — the upcoming sherpa-onnx / future iGPU backends
  reuse the same hallucination blocklist and RMS floor; centralising them
  here lets each backend wire in the same postprocess without copying code.

The contract is **behavioural parity** with the pre-refactor inline code in
``transcribe_array``. ``transcriber.py`` re-exports each helper under its
old ``_``-prefixed name so existing import sites keep working.
"""
from __future__ import annotations

import math

# ``numpy`` is required at call time for the audio helpers but kept out of
# the module-level imports so the hallucination / confidence helpers can be
# imported on a numpy-less environment (none such exists in this project,
# but it keeps the dependency surface honest).


# --------------------------------------------------------------------------- #
# RMS / VAD                                                                   #
# --------------------------------------------------------------------------- #

# float32 [-1, 1] base, ≈ -46 dBFS. 実発話は概ね RMS > 0.05 のため誤除外しない。
# これ未満の RMS は無音とみなし STT に渡さない (Whisper のハルシネーション源を断つ)。
HALLUCINATION_SILENCE_RMS: float = 0.005


def _rms(audio) -> float:
    """Root-mean-square of a float32 mono audio array. Returns 0.0 for empty input."""
    import numpy as np

    if audio.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(audio))))


def is_voice(audio, sample_rate: int = 16000) -> bool:
    """True if the audio RMS reaches the silence floor (likely contains voice).

    ``sample_rate`` is currently unused — the floor is amplitude-based, not
    frequency-based — but accepted in the signature so a future spectral VAD
    upgrade can land without breaking the call sites.
    """
    _ = sample_rate  # API placeholder for future spectral VAD
    return _rms(audio) >= HALLUCINATION_SILENCE_RMS


def apply_rms_floor(audio) -> list | None:
    """Silence early-return guard.

    Returns ``[]`` (an empty segment list, ready to be returned by the caller)
    when audio RMS is below :data:`HALLUCINATION_SILENCE_RMS`, otherwise
    ``None`` to signal "proceed with real transcription".

    Usage in ``transcribe_array``::

        early = apply_rms_floor(audio)
        if early is not None:
            return early
        # ... run faster-whisper on the (non-silent) chunk
    """
    if not is_voice(audio):
        return []
    return None


# --------------------------------------------------------------------------- #
# Hallucination blocklist                                                     #
# --------------------------------------------------------------------------- #


# Sentence-final punctuation to strip from both ends, in both half-width
# (ASCII) and full-width (JIS) forms; the full-width forms are *required*
# for Japanese matching and are intentional (ruff RUF001 silenced).
_TRAILING_PUNCT = (
    "。.!！?？、,， 　　"  # noqa: RUF001 — JP punctuation needs full-width forms
)


def normalize_for_hallucination_check(text: str) -> str:
    """Trim whitespace + trailing JP/EN punctuation so equivalent phrasings collide.

    The set kept in :data:`HALLUCINATION_NORM` is pre-normalised with this
    function; callers must run text through the same normaliser before
    membership testing (which :func:`should_filter_hallucination` does).
    """
    # `str.strip(chars)` removes ANY of the characters in `chars` from both
    # ends — that is exactly the behaviour we want (drop a trailing 。 or !
    # or a comma); B005 no longer fires because `_TRAILING_PUNCT` is a name,
    # not a string literal, so ruff cannot prove the multi-char misuse.
    return text.strip().strip(_TRAILING_PUNCT)


# Whisper が無音/低レベル音声で生成しがちな定型ハルシネーション (YouTube 由来)。
# セグメント全体がこれらに一致するときのみ除外する (実発話の部分文字列は除外しない)。
# 注: 「ご清聴ありがとうございました」は実会議の締めで出るため意図的に含めない。
HALLUCINATION_NORM: frozenset[str] = frozenset(
    normalize_for_hallucination_check(p)
    for p in (
        "ご視聴ありがとうございました",
        "ご視聴ありがとうございます",
        "ご視聴いただきありがとうございました",
        "最後までご視聴いただきありがとうございました",
        "チャンネル登録お願いします",
        "チャンネル登録をお願いします",
        "チャンネル登録よろしくお願いします",
    )
)


def should_filter_hallucination(text: str) -> bool:
    """Whole-segment match against the YouTube-style hallucination blocklist.

    Only triggers when the *entire* (normalised) segment text equals a
    blocklisted phrase. A real sentence that contains a blocklisted phrase
    as a substring is NOT filtered.
    """
    return normalize_for_hallucination_check(text) in HALLUCINATION_NORM


# --------------------------------------------------------------------------- #
# Confidence mapping                                                          #
# --------------------------------------------------------------------------- #


def logprob_to_confidence(avg_logprob: float) -> float:
    """Map faster-whisper ``avg_logprob`` (-inf..0) to a 0..1 confidence score.

    The result is clamped to the unit interval so a pathological positive
    logprob (defensive — faster-whisper never produces one) does not propagate
    a >1.0 confidence into the UI.
    """
    return max(0.0, min(1.0, math.exp(avg_logprob)))
