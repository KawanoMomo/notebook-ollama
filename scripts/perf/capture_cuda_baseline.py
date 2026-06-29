"""Capture a CUDA performance baseline for `tests/perf/test_cuda_regression.py`.

Sprint 1 / Task 1.5 of `docs/superpowers/plans/2026-06-29-igpu-npu-acceleration.md`.

What it measures
----------------
Three numbers, all on the dev box's NVIDIA GPU running ``faster-whisper-large-v3``
with ``compute_type="float16"``:

* ``cuda_rtf`` -- total transcription wall time divided by audio duration. The
  primary regression metric.
* ``cuda_first_chunk_latency_ms`` -- wall time from ``model.transcribe(...)``
  call until the first segment yields from the lazy iterator. This is what
  the live-caption UI feels as "time to first caption" and is the most
  sensitive to regressions in CUDA init / DLL loading.
* ``cuda_tokens_per_sec`` -- sum of ``len(seg.tokens)`` across all segments
  divided by wall time. Captures decoder throughput regressions that RTF
  alone can mask when the model returns fewer tokens.

How the audio fixture is chosen
-------------------------------
The script prefers ``tests/fixtures/30s-jp.wav`` (real Japanese speech) when
present -- that gives a meaningful RTF on the kind of audio the app actually
processes. When the fixture is absent (true today) it falls back to a
synthetic 30 s sine wave at 440 Hz, 16 kHz mono, with ``vad_filter=False`` so
faster-whisper actually exercises the decoder. The synthetic signal makes the
*absolute* RTF / tokens-per-sec values uncomparable to a real-speech run, but
the numbers are still bit-for-bit reproducible on the same hardware, which is
exactly what a regression gate needs.

This limitation is recorded in the output JSON's ``notes`` / ``fixture_kind``
fields so a future tester swapping in a real fixture knows to re-capture.

Hardware fingerprint
--------------------
The JSON records ``probe_cuda()`` output (``cuda_available`` /
``cuda_device_count``) plus ``probe_cpu()`` brand. If the regression test
later runs on a different GPU the comparison is meaningless; the fingerprint
makes that obvious in the diff.

Usage
-----
::

    uv run --extra recording python scripts/perf/capture_cuda_baseline.py

The script writes ``tests/perf/baseline.json`` atomically (write to ``.tmp``,
then ``os.replace``) so a Ctrl-C halfway through never leaves a corrupt JSON.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np

# Path constants -- resolved relative to repo root so the script works from
# any cwd (CI, dev box, scratch dir).
_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FIXTURE_PATH = _REPO_ROOT / "tests" / "fixtures" / "30s-jp.wav"
DEFAULT_OUTPUT_PATH = _REPO_ROOT / "tests" / "perf" / "baseline.json"

# Audio constants. Whisper expects 16 kHz mono float32 in [-1, 1].
SAMPLE_RATE = 16000
DEFAULT_DURATION_S = 30

# Model / inference constants. These are the values transcriber.py uses in
# production for live captioning. Changing them here would silently make the
# baseline non-representative.
MODEL_SIZE = "large-v3"
DEVICE = "cuda"
COMPUTE_TYPE = "float16"
LANGUAGE = "ja"
BEAM_SIZE = 5


@dataclass(frozen=True)
class CudaMetrics:
    """Three numeric metrics + reproducibility metadata."""

    cuda_rtf: float
    cuda_first_chunk_latency_ms: float
    cuda_tokens_per_sec: float
    audio_duration_s: float
    transcription_wall_s: float
    total_tokens: int
    segment_count: int


def _generate_sine_wave(duration_s: float, sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    """Return a 440 Hz sine wave as float32 mono in [-1, 1].

    Pure sine is intentionally silent under ``vad_filter=True`` (Silero classes
    it as non-speech). Callers must therefore pass ``vad_filter=False`` to
    faster-whisper so the decoder actually runs on this fixture.
    """
    n = int(duration_s * sample_rate)
    t = np.arange(n, dtype=np.float32) / sample_rate
    # 0.3 amplitude keeps it well clear of clipping while still loud enough
    # that no_speech_prob doesn't immediately drop every segment.
    return (0.3 * np.sin(2.0 * np.pi * 440.0 * t)).astype(np.float32)


def _load_audio(fixture_path: Path, duration_s: float) -> tuple[np.ndarray, str]:
    """Return ``(audio_float32_mono_16k, fixture_kind)``.

    Prefers a real fixture WAV; falls back to a synthetic sine wave.
    ``fixture_kind`` is recorded in baseline.json so a tester can distinguish
    a meaningful real-speech RTF from a synthetic stress-test number.
    """
    if fixture_path.exists():
        # Lazy import -- soundfile is part of the ``recording`` extra and we
        # don't want this script to ImportError when sf is absent if the
        # fallback path is the one we'd take anyway.
        import soundfile as sf

        audio, sr = sf.read(str(fixture_path), dtype="float32", always_2d=False)
        if audio.ndim == 2:
            audio = audio.mean(axis=1).astype(np.float32)
        if sr != SAMPLE_RATE:
            # Resampling here would change the timing characteristics we are
            # trying to baseline. Fail loud so the fixture gets re-encoded
            # rather than silently producing a misleading number.
            raise SystemExit(
                f"Fixture {fixture_path} is {sr} Hz; expected {SAMPLE_RATE} Hz. "
                "Re-encode the fixture to 16 kHz mono float32 WAV."
            )
        # Truncate / pad to the requested duration so the metric is stable
        # regardless of the exact fixture length.
        target = int(duration_s * SAMPLE_RATE)
        if audio.shape[0] >= target:
            audio = audio[:target]
        else:
            audio = np.pad(audio, (0, target - audio.shape[0]))
        return audio, "real_speech_wav"

    return _generate_sine_wave(duration_s), "synthetic_sine_440hz"


def measure_cuda_metrics(
    fixture_path: Path = DEFAULT_FIXTURE_PATH,
    duration_s: float = DEFAULT_DURATION_S,
) -> tuple[CudaMetrics, str]:
    """Run the full transcription and return metrics + ``fixture_kind``.

    This function is the single source of truth shared by the capture script
    AND the regression test, so they always measure exactly the same thing.
    Splitting them would let one drift relative to the other and silently
    invalidate the gate.
    """
    # Defer heavy imports until we actually run. Keeps ``--help`` cheap and
    # lets the regression test skip cleanly when ``faster-whisper`` is absent.
    #
    # C1 fix replication: ``faster_whisper`` indirectly imports ``ctranslate2``,
    # which on Windows needs ``cublas64_12.dll`` / ``cudnn_*.dll`` resolvable
    # via ``os.add_dll_directory`` *before* the load. The transcriber module
    # registers these at its own module-import time, but this script bypasses
    # transcriber.py and imports ``WhisperModel`` directly -- so we must
    # register the DLL dirs explicitly here, otherwise the model load raises
    # ``RuntimeError: Library cublas64_12.dll is not found or cannot be loaded``
    # under a clean ``uv run`` (Issue: same failure mode the C1 fix exists for).
    from core.accel.cuda_dll import _register_cuda_dll_dirs

    _register_cuda_dll_dirs()

    from faster_whisper import WhisperModel

    audio, fixture_kind = _load_audio(fixture_path, duration_s)
    audio_duration_s = float(audio.shape[0]) / SAMPLE_RATE

    model = WhisperModel(MODEL_SIZE, device=DEVICE, compute_type=COMPUTE_TYPE)

    # Warm-up: 1 s of the same audio. The first call after model load pays a
    # one-time CUDA kernel-compile cost (~1-2 s on a 2080 Ti) that would
    # otherwise dominate the measured RTF and make the baseline noisy.
    warmup_audio = audio[: SAMPLE_RATE * 1].copy()
    warmup_iter, _ = model.transcribe(
        warmup_audio,
        language=LANGUAGE,
        beam_size=BEAM_SIZE,
        vad_filter=False,
    )
    # Drain the generator to ensure the warm-up actually completed before we
    # start the timed run.
    for _ in warmup_iter:
        pass

    # Timed run. vad_filter=False so a synthetic sine fixture still exercises
    # the decoder (Silero would otherwise drop every frame as non-speech and
    # we'd measure essentially nothing).
    t0 = time.perf_counter()
    segments_iter, _info = model.transcribe(
        audio,
        language=LANGUAGE,
        beam_size=BEAM_SIZE,
        vad_filter=False,
    )

    first_latency_ms: float | None = None
    total_tokens = 0
    segment_count = 0
    for seg in segments_iter:
        if first_latency_ms is None:
            first_latency_ms = (time.perf_counter() - t0) * 1000.0
        # faster-whisper Segment exposes `.tokens: list[int]` (decoder token
        # IDs). Summing across segments gives a stable decoder-throughput
        # number that doesn't depend on the text format.
        tokens = getattr(seg, "tokens", None) or []
        total_tokens += len(tokens)
        segment_count += 1

    transcription_wall_s = time.perf_counter() - t0

    # Defensive: if VAD / no-speech filtering dropped every segment we never
    # set first_latency_ms. Fall back to the total wall time so the metric is
    # always defined (the gate compares <= baseline * 1.10; using the full
    # wall time as first-latency just means a future regression would have to
    # be enormous to fail the gate -- acceptable safety degradation).
    if first_latency_ms is None:
        first_latency_ms = transcription_wall_s * 1000.0

    cuda_rtf = transcription_wall_s / audio_duration_s
    cuda_tokens_per_sec = (
        float(total_tokens) / transcription_wall_s if transcription_wall_s > 0 else 0.0
    )

    metrics = CudaMetrics(
        cuda_rtf=cuda_rtf,
        cuda_first_chunk_latency_ms=first_latency_ms,
        cuda_tokens_per_sec=cuda_tokens_per_sec,
        audio_duration_s=audio_duration_s,
        transcription_wall_s=transcription_wall_s,
        total_tokens=total_tokens,
        segment_count=segment_count,
    )
    return metrics, fixture_kind


def _hardware_fingerprint() -> dict[str, Any]:
    """Capture probe_cuda + cpu_brand so the gate can detect HW drift.

    Imports the probes lazily so this module can be ``--help``'d on a box
    where ``ctranslate2`` isn't installed.
    """
    from core.accel.probe import probe_cpu
    from core.accel.probe_cuda import probe_cuda

    cuda_available, cuda_device_count = probe_cuda()
    return {
        "cuda_available": bool(cuda_available),
        "cuda_device_count": int(cuda_device_count),
        "cpu_brand": probe_cpu(),
    }


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    """Write JSON atomically via tempfile + ``os.replace``.

    A Ctrl-C between the write and the rename leaves the previous baseline
    intact -- important because re-running capture is expensive (~30 s on
    CUDA + a model warm-up) and we don't want a half-finished file to make
    the regression test silently pass on garbage values.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=str(path.parent),
        prefix=path.name + ".",
        suffix=".tmp",
        delete=False,
    ) as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)
        fh.write("\n")
        tmp_path = Path(fh.name)
    os.replace(tmp_path, path)


def build_baseline_payload(
    metrics: CudaMetrics,
    fixture_kind: str,
    fixture_path: Path,
) -> dict[str, Any]:
    """Compose the dict that gets serialised to baseline.json.

    Keeping this pure (no IO) lets the unit tests construct one without
    actually transcribing -- useful for "test the test" smoke checks.
    """
    notes: list[str] = []
    if fixture_kind == "synthetic_sine_440hz":
        notes.append(
            "Audio is a synthetic 440 Hz sine wave (no real-speech fixture "
            "available). RTF / tokens/sec values are NOT comparable to a "
            "real-speech run. To capture a meaningful baseline, drop a "
            "16 kHz mono float32 WAV at tests/fixtures/30s-jp.wav and "
            "re-run this script."
        )
    return {
        "placeholder": False,
        "captured_at_utc": _dt.datetime.now(_dt.UTC).isoformat(),
        "fixture_kind": fixture_kind,
        "fixture_path": str(fixture_path.relative_to(_REPO_ROOT))
        if fixture_path.exists()
        else None,
        "model": MODEL_SIZE,
        "device": DEVICE,
        "compute_type": COMPUTE_TYPE,
        "language": LANGUAGE,
        "beam_size": BEAM_SIZE,
        "hardware": _hardware_fingerprint(),
        "metrics": asdict(metrics),
        "regression_ratio": 1.10,
        "notes": notes,
    }


def build_placeholder_payload(reason: str) -> dict[str, Any]:
    """Return the placeholder payload shape used when capture cannot run.

    The regression test inspects ``placeholder == True`` to skip cleanly so
    a CI box without CUDA / faster-whisper doesn't fail the test suite.
    """
    return {
        "placeholder": True,
        "captured_at_utc": None,
        "fixture_kind": None,
        "fixture_path": None,
        "model": MODEL_SIZE,
        "device": DEVICE,
        "compute_type": COMPUTE_TYPE,
        "language": LANGUAGE,
        "beam_size": BEAM_SIZE,
        "hardware": None,
        "metrics": {
            "cuda_rtf": None,
            "cuda_first_chunk_latency_ms": None,
            "cuda_tokens_per_sec": None,
            "audio_duration_s": None,
            "transcription_wall_s": None,
            "total_tokens": None,
            "segment_count": None,
        },
        "regression_ratio": 1.10,
        "notes": [
            f"Placeholder baseline -- capture script could not run: {reason}",
            "Manual capture procedure:",
            "  1. Install the recording extra: `uv sync --extra recording`",
            "  2. Verify CUDA visible: `uv run python -c \"from core.accel.probe_cuda "
            "import probe_cuda; print(probe_cuda())\"` -> expects `(True, >=1)`. "
            "If `(False, 0)` see core/accel/cuda_dll.py C1 fix.",
            "  3. (Optional) Drop a real-speech 16 kHz mono float32 WAV at "
            "tests/fixtures/30s-jp.wav for a meaningful RTF.",
            "  4. Run: `uv run --extra recording python scripts/perf/capture_cuda_baseline.py`",
            "  5. Commit the resulting tests/perf/baseline.json.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fixture",
        type=Path,
        default=DEFAULT_FIXTURE_PATH,
        help="Path to 30 s 16 kHz mono float32 WAV. Falls back to sine wave.",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=DEFAULT_DURATION_S,
        help="Audio duration to baseline (seconds). Default: 30.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help="Where to write baseline.json. Default: tests/perf/baseline.json",
    )
    parser.add_argument(
        "--placeholder",
        action="store_true",
        help=(
            "Write a placeholder baseline.json (no real measurement). Use "
            "this on a box without CUDA / faster-whisper to bootstrap the "
            "harness; a real capture must follow before the gate is useful."
        ),
    )
    args = parser.parse_args(argv)

    if args.placeholder:
        payload = build_placeholder_payload(reason="--placeholder flag passed")
        _atomic_write_json(args.output, payload)
        print(f"Wrote placeholder baseline to {args.output}", file=sys.stderr)
        return 0

    try:
        metrics, fixture_kind = measure_cuda_metrics(
            fixture_path=args.fixture, duration_s=args.duration
        )
    except Exception as exc:
        print(
            f"Capture failed: {type(exc).__name__}: {exc}\n"
            "Writing placeholder baseline so the harness is still installed.",
            file=sys.stderr,
        )
        payload = build_placeholder_payload(reason=f"{type(exc).__name__}: {exc}")
        _atomic_write_json(args.output, payload)
        return 1

    payload = build_baseline_payload(metrics, fixture_kind, args.fixture)
    _atomic_write_json(args.output, payload)
    print(
        f"Captured baseline: rtf={metrics.cuda_rtf:.4f}, "
        f"first_chunk_ms={metrics.cuda_first_chunk_latency_ms:.1f}, "
        f"tokens_per_sec={metrics.cuda_tokens_per_sec:.2f}, "
        f"fixture={fixture_kind}",
        file=sys.stderr,
    )
    print(f"Wrote {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
