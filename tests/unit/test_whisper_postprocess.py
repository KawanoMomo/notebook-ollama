"""Unit tests for `core.recording.whisper_postprocess`.

These helpers were extracted from `core/recording/transcriber.py` (Sprint 3 /
Task 3.1) so they can be unit-tested without loading faster-whisper /
ctranslate2 / CUDA drivers. Behavioural parity with the pre-refactor inline
logic is the success criterion — anything that changes the *result* of the
filter / RMS check is a regression even if the new behaviour seems "better".
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from core.recording.whisper_postprocess import (
    HALLUCINATION_NORM,
    HALLUCINATION_SILENCE_RMS,
    apply_rms_floor,
    is_voice,
    logprob_to_confidence,
    normalize_for_hallucination_check,
    should_filter_hallucination,
)

# --------------------------------------------------------------------------- #
# Hallucination blocklist                                                     #
# --------------------------------------------------------------------------- #


def test_hallucination_norm_contains_canonical_phrases():
    """Canonical Japanese YouTube hallucinations must be in the blocklist
    AFTER normalisation (so callers don't have to re-normalize)."""
    canonical = {
        "ご視聴ありがとうございました",
        "ご視聴ありがとうございます",
        "ご視聴いただきありがとうございました",
        "最後までご視聴いただきありがとうございました",
        "チャンネル登録お願いします",
        "チャンネル登録をお願いします",
        "チャンネル登録よろしくお願いします",
    }
    normalized = {normalize_for_hallucination_check(s) for s in canonical}
    assert normalized.issubset(HALLUCINATION_NORM)


def test_hallucination_norm_excludes_real_closing_phrase():
    """『ご清聴ありがとうございました』 is intentionally NOT blocked because
    real meetings end with it; only the YouTube-shaped 『ご視聴…』 is filtered."""
    closer = normalize_for_hallucination_check("ご清聴ありがとうございました")
    assert closer not in HALLUCINATION_NORM


def test_should_filter_hallucination_blocks_known_phrase():
    assert should_filter_hallucination("ご視聴ありがとうございました") is True


def test_should_filter_hallucination_blocks_with_trailing_punctuation():
    """Normalisation strips trailing punctuation, so the same phrase with
    a period / exclamation point still matches.

    Full-width punctuation here is intentional — it is what Whisper actually
    emits for Japanese audio, so the test data is the real-world shape.
    """
    assert should_filter_hallucination("ご視聴ありがとうございました。") is True
    assert should_filter_hallucination("ご視聴ありがとうございました！") is True  # noqa: RUF001


def test_should_filter_hallucination_passes_real_speech():
    assert should_filter_hallucination("これは普通の発話です") is False
    assert should_filter_hallucination("ご清聴ありがとうございました") is False


def test_should_filter_hallucination_does_not_match_substring():
    """Only whole-segment matches are filtered — a real sentence that happens
    to contain a blocklisted phrase must NOT be dropped."""
    longer = "今日はご視聴ありがとうございましたという挨拶について話します"
    assert should_filter_hallucination(longer) is False


def test_normalize_for_hallucination_check_strips_whitespace_and_punct():
    assert normalize_for_hallucination_check("  hello  ") == "hello"
    assert normalize_for_hallucination_check("hi。") == "hi"
    assert normalize_for_hallucination_check("hi! ") == "hi"


# --------------------------------------------------------------------------- #
# VAD / RMS floor                                                             #
# --------------------------------------------------------------------------- #


def test_is_voice_false_for_silence():
    audio = np.zeros(16000, dtype=np.float32)
    assert is_voice(audio, sample_rate=16000) is False


def test_is_voice_false_for_empty():
    audio = np.zeros(0, dtype=np.float32)
    assert is_voice(audio, sample_rate=16000) is False


def test_is_voice_true_for_loud_signal():
    audio = (np.random.RandomState(42).randn(16000) * 0.3).astype(np.float32)
    assert is_voice(audio, sample_rate=16000) is True


def test_is_voice_threshold_above_floor():
    """RMS slightly above the silence floor must register as voice.

    Mirrors the pre-refactor predicate ``rms < floor → silence`` exactly:
    anything not strictly below the floor counts as voice. We use 1.5x the
    floor to stay clear of float32 quantisation noise around the boundary.
    """
    audio = np.full(16000, HALLUCINATION_SILENCE_RMS * 1.5, dtype=np.float32)
    assert is_voice(audio) is True


def test_is_voice_just_below_floor_is_silence():
    """RMS just below the floor → silence (parity with pre-refactor `<`)."""
    audio = np.full(16000, HALLUCINATION_SILENCE_RMS * 0.5, dtype=np.float32)
    assert is_voice(audio) is False


def test_apply_rms_floor_returns_empty_for_silence():
    audio = np.zeros(16000, dtype=np.float32)
    assert apply_rms_floor(audio) == []


def test_apply_rms_floor_returns_empty_for_empty_audio():
    audio = np.zeros(0, dtype=np.float32)
    assert apply_rms_floor(audio) == []


def test_apply_rms_floor_returns_none_for_voice():
    """None signals 'proceed with real transcription' to the caller."""
    audio = (np.random.RandomState(7).randn(16000) * 0.3).astype(np.float32)
    assert apply_rms_floor(audio) is None


# --------------------------------------------------------------------------- #
# Confidence mapping                                                          #
# --------------------------------------------------------------------------- #


def test_logprob_to_confidence_zero_is_one():
    assert logprob_to_confidence(0.0) == pytest.approx(1.0)


def test_logprob_to_confidence_negative_decays():
    """avg_logprob = -1 → confidence = exp(-1) ≈ 0.368."""
    assert logprob_to_confidence(-1.0) == pytest.approx(math.exp(-1.0))


def test_logprob_to_confidence_clamped_to_unit_interval():
    """Defensive: a pathological positive logprob (shouldn't happen) is
    clamped to 1.0; very negative is clamped to 0.0."""
    assert logprob_to_confidence(10.0) == 1.0
    assert logprob_to_confidence(-1e9) == pytest.approx(0.0)


# --------------------------------------------------------------------------- #
# Back-compat shim: transcriber.py must re-export everything                  #
# --------------------------------------------------------------------------- #


def test_transcriber_reexports_helpers_for_backward_compat():
    """Existing call sites import these names from `core.recording.transcriber`;
    the refactor must keep the names importable from the old location."""
    from core.recording import transcriber as t

    assert t._HALLUCINATION_NORM is HALLUCINATION_NORM
    assert t._HALLUCINATION_SILENCE_RMS == HALLUCINATION_SILENCE_RMS
    assert t._normalize_caption("ご視聴ありがとうございました。") == "ご視聴ありがとうございました"
    assert t._is_hallucination_phrase("ご視聴ありがとうございました") is True
    assert t._logprob_to_confidence(0.0) == pytest.approx(1.0)
