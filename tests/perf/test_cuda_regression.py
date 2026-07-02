"""CUDA perf regression gate (Sprint 1 / Task 1.5).

Compares fresh measurements from ``scripts.perf.capture_cuda_baseline.measure_cuda_metrics``
against the committed ``tests/perf/baseline.json`` and fails when any metric
regresses by more than ``regression_ratio`` (default 1.10, i.e. 10 % slack).

Why share the measurement function with the capture script
----------------------------------------------------------
Capture and test MUST measure the same thing or the gate is meaningless. We
import ``measure_cuda_metrics`` from the capture script rather than duplicating
the timing logic, so any change to warm-up / VAD flags / token-counting flows
to both sides at once.

Skip behaviour
--------------
The gate is opt-in via ``-m "cuda and slow"``. On top of that, every test
skips cleanly when:

* ``baseline.json`` does not exist (harness installed but never captured).
* ``baseline.json`` is a placeholder (``{"placeholder": true, ...}``) -- a
  CI box without CUDA can bootstrap the harness file without failing.
* ``faster-whisper`` is not installed (the ``recording`` extra wasn't synced).
* ``probe_cuda()`` reports no CUDA device (the test box is CPU-only).

Skipping silently for "no CUDA" is correct here because the marker filter
already gates this file; if a user explicitly ran ``-m "cuda and slow"`` on a
CPU box the skip message makes the cause obvious.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

BASELINE_PATH = Path(__file__).parent / "baseline.json"


# --------------------------------------------------------------------------- #
# Shared fixtures                                                             #
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def baseline() -> dict[str, Any]:
    """Load baseline.json, skipping cleanly on missing / placeholder files."""
    if not BASELINE_PATH.exists():
        pytest.skip(
            f"{BASELINE_PATH} does not exist -- run "
            "`uv run --extra recording python scripts/perf/capture_cuda_baseline.py` "
            "to capture a baseline first."
        )
    data = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    if data.get("placeholder"):
        pytest.skip(
            "baseline.json is a placeholder -- a real capture has not yet been "
            "performed on this hardware. See the `notes` field in the file "
            "for the manual capture procedure."
        )
    return data


@pytest.fixture(scope="module")
def fresh_metrics(baseline: dict[str, Any]):
    """Run a single fresh capture and share it across the three gate tests.

    Module-scoped so all three metrics are checked against the SAME run.
    Otherwise each test would re-load ``large-v3`` and re-transcribe (~30 s
    x 3 on a 2080 Ti), which would dominate the CI clock and -- worse -- three
    independent runs would give three slightly-different RTF values that
    obscure whether a single bad run or a real regression caused the fail.
    """
    try:
        from scripts.perf.capture_cuda_baseline import measure_cuda_metrics
    except ImportError as exc:
        pytest.skip(f"capture script unavailable: {exc}")

    # Re-check CUDA at run time -- the marker filter is opt-in but a developer
    # may force-run with ``-m "cuda and slow"`` on a CPU-only box. Skipping
    # here with a clear message beats a cryptic ctranslate2 error.
    try:
        from core.accel.probe_cuda import probe_cuda
    except ImportError as exc:
        pytest.skip(f"core.accel.probe_cuda unavailable: {exc}")

    cuda_ok, n = probe_cuda()
    if not cuda_ok or n < 1:
        pytest.skip(
            "probe_cuda() reported no CUDA device -- cannot run a CUDA "
            "regression test on this host."
        )

    try:
        # Use the same fixture / duration the baseline was captured with, so
        # the comparison is apples-to-apples. ``measure_cuda_metrics``'s
        # defaults already match the script defaults; we pass them through
        # explicitly so a future change to the defaults makes the mismatch
        # obvious in this test.
        from scripts.perf.capture_cuda_baseline import (
            DEFAULT_DURATION_S,
            DEFAULT_FIXTURE_PATH,
        )

        metrics, fixture_kind = measure_cuda_metrics(
            fixture_path=DEFAULT_FIXTURE_PATH,
            duration_s=DEFAULT_DURATION_S,
        )
    except ImportError as exc:
        pytest.skip(f"faster-whisper or recording deps not installed: {exc}")

    if fixture_kind != baseline.get("fixture_kind"):
        pytest.skip(
            f"Fixture kind drift: baseline captured with "
            f"{baseline.get('fixture_kind')!r}, current run got "
            f"{fixture_kind!r}. Re-capture baseline to compare apples-to-apples."
        )
    return metrics


def _ratio(baseline: dict[str, Any]) -> float:
    """Slack ratio recorded in baseline.json. Defaults to 1.10 = 10 %."""
    return float(baseline.get("regression_ratio", 1.10))


# --------------------------------------------------------------------------- #
# The three gates                                                              #
# --------------------------------------------------------------------------- #


@pytest.mark.cuda
@pytest.mark.slow
def test_cuda_rtf_within_baseline(fresh_metrics, baseline):
    """RTF gate: ``new_rtf <= baseline_rtf * 1.10`` (lower RTF = faster).

    RTF is the primary user-facing metric: an RTF of 0.1 means the GPU
    transcribes 10 s of audio per real-time second, so two live-caption
    streams (mic + system) at RTF<=0.5 stay ahead of real time. A 10 %
    regression of a 0.1 RTF baseline still leaves comfortable headroom; a
    regression worse than that is the threshold at which mic/system can
    start falling behind during peak load.
    """
    baseline_rtf = baseline["metrics"]["cuda_rtf"]
    ratio = _ratio(baseline)
    threshold = baseline_rtf * ratio
    assert fresh_metrics.cuda_rtf <= threshold, (
        f"CUDA RTF regression: new={fresh_metrics.cuda_rtf:.4f} > "
        f"baseline {baseline_rtf:.4f} * {ratio} = {threshold:.4f}. "
        "Investigate recent changes to transcriber init / CUDA DLL loading."
    )


@pytest.mark.cuda
@pytest.mark.slow
def test_cuda_first_chunk_latency_within_baseline(fresh_metrics, baseline):
    """First-chunk latency gate: ``new_ms <= baseline_ms * 1.10`` (lower = faster).

    This metric is what the user *feels* as "time to first caption". The
    typical regression source is CUDA init: missing DLL search-path
    registration (see C1 fix in core/accel/cuda_dll.py) can push first-chunk
    latency from ~1 s to ~5 s because cuBLAS / cuDNN fall back to a slow
    path, while RTF on the steady-state remains acceptable.
    """
    baseline_ms = baseline["metrics"]["cuda_first_chunk_latency_ms"]
    ratio = _ratio(baseline)
    threshold = baseline_ms * ratio
    assert fresh_metrics.cuda_first_chunk_latency_ms <= threshold, (
        f"CUDA first-chunk latency regression: "
        f"new={fresh_metrics.cuda_first_chunk_latency_ms:.1f} ms > "
        f"baseline {baseline_ms:.1f} ms * {ratio} = {threshold:.1f} ms. "
        "Investigate CUDA init / DLL-loading path."
    )


@pytest.mark.cuda
@pytest.mark.slow
def test_cuda_tokens_per_sec_within_baseline(fresh_metrics, baseline):
    """Throughput gate: ``new_tps >= baseline_tps / 1.10`` (higher = faster).

    Inverse direction from RTF / latency: tokens/sec going *down* is the
    regression. We divide rather than multiply so the gate is symmetric with
    the other two -- a 10 % drop in tokens/sec is the failure threshold,
    matching a 10 % rise in RTF.

    Catches regressions where total transcription time is unchanged but the
    decoder is generating fewer tokens (e.g. a sampling-param drift that
    early-stops segments).
    """
    baseline_tps = baseline["metrics"]["cuda_tokens_per_sec"]
    if baseline_tps <= 0:
        pytest.skip(
            "Baseline tokens_per_sec is zero -- fixture produced no decoder "
            "output. Re-capture with a fixture that actually transcribes."
        )
    ratio = _ratio(baseline)
    floor = baseline_tps / ratio
    assert fresh_metrics.cuda_tokens_per_sec >= floor, (
        f"CUDA tokens/sec regression: "
        f"new={fresh_metrics.cuda_tokens_per_sec:.2f} < "
        f"baseline {baseline_tps:.2f} / {ratio} = {floor:.2f}. "
        "Investigate decoder sampling params or model load path."
    )
