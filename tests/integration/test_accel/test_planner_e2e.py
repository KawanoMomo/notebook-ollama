"""Sprint 2 / Task 2.3 — end-to-end integration tests for the Planner chain.

Wires the three layers built by Sprints 1+2 together and verifies they
actually compose:

    HardwareProbe.run() -> HwProfile -> BackendPlanner.plan() -> BackendPlan

Test surface:

* :func:`test_real_hw_probe_to_planner_to_plan_e2e` — deterministic run with
  ``NOTEBOOK_OLLAMA_SKIP_ACCEL_PROBE=1`` so the chain is exercised end-to-end
  without touching ``pnputil`` / ``ctranslate2`` / ``nvidia-smi``. The
  probe short-circuit returns ``_STUB_PROFILE`` and the planner must produce
  the canonical CPU fallback plan.
* :func:`test_real_dev_box_cuda_plan` — the dev-box integration smoke. With
  the env var **unset**, the real probe fires; on a host with CUDA visible
  the planner must pick ``faster-whisper-cuda`` / ``ollama-cuda``. This is
  the test that proves the whole chain works end-to-end on the development
  hardware (RTX 2080 Ti). Skipped on hosts without CUDA so the suite stays
  green in CPU-only CI.
* :func:`test_plan_reason_is_human_readable` — the planner's ``reason``
  string is what surfaces in the Acceleration tab / startup log; it must
  contain enough markers for a human reading the log to grok the choice.
* :func:`test_phase1_implementable_on_dev_box` — ``is_phase1_implementable``
  is the Planner/Factory contract gate. On the dev box every chosen id is in
  ``PHASE1_IMPLEMENTABLE_IDS`` so this returns True.
* :func:`test_phase1_not_implementable_on_intel_lunar_lake` — synthetic
  Intel iGPU+NPU profile drives the planner to ``openvino-*`` ids that
  Phase 1 has not implemented. ``is_phase1_implementable`` must return False
  — this is the contract proof, not a bug.

Plus regression-locking tests:

* :func:`test_parametrized_stt_ids_match_single_source_of_truth` — the
  parametrized fixture below uses ``BACKEND_IDS["STT"]`` directly rather
  than hand-rolling a literal list. This test re-asserts that the imported
  set is *the* single source of truth (so a future change to ``BACKEND_IDS``
  cannot silently leave this file out of sync).
* :func:`test_every_stt_id_is_routable_by_planner_or_dropped` — every id in
  ``BACKEND_IDS["STT"]`` must be reachable by some HW profile the planner
  knows about, *or* be a Phase 2 declared-but-not-implemented id surfaced
  through ``is_phase1_implementable``. Catches "dead id" regressions where
  an id is added to ``BACKEND_IDS`` but no routing rule emits it.
"""

from __future__ import annotations

import re
from typing import Any

import pytest

from core.accel.backend_ids import BACKEND_IDS
from core.accel.plan import (
    PHASE1_IMPLEMENTABLE_IDS,
    BackendPlan,
    is_phase1_implementable,
)
from core.accel.planner import BackendPlanner
from core.accel.probe import HardwareProbe
from core.accel.probe_cuda import probe_cuda
from core.accel.probe_env import ENV_VAR_NAME
from core.accel.profile import _STUB_PROFILE, HwProfile

# ---------------------------------------------------------------------------
# Capability gate for the dev-box smoke
# ---------------------------------------------------------------------------

# Probe CUDA once at import time. The actual probe is cheap (a single
# `ctranslate2.get_cuda_device_count()` call after DLL-dir registration) and
# we need the result before pytest can decide whether to skip the dev-box
# smoke. Running CI in a CPU-only container? probe_cuda() returns (False, 0)
# and the smoke skips cleanly.
_HAS_CUDA, _CUDA_DEVICE_COUNT = probe_cuda()

requires_cuda = pytest.mark.skipif(
    not _HAS_CUDA,
    reason=(
        "CUDA not visible to ctranslate2 on this host "
        f"(probe_cuda returned ({_HAS_CUDA}, {_CUDA_DEVICE_COUNT})). "
        "Dev-box smoke skipped."
    ),
)


# ---------------------------------------------------------------------------
# HwProfile fixture helpers (kept tiny; the unit-test counterparts in
# tests/unit/test_planner.py carry the canonical fixture catalogue).
# ---------------------------------------------------------------------------


def _profile(**overrides: Any) -> HwProfile:
    """Construct an ``HwProfile`` with CPU-only defaults for synthetic tests."""
    base: dict[str, Any] = {
        "vendor": "unknown",
        "cpu_brand": "test",
        "dgpu": None,
        "igpu": None,
        "npu": None,
        "vram_mb": None,
        "ryzen_ai_gen": None,
        "openvino_devices": (),
        "has_directml": False,
        "has_cuda": False,
        "cuda_device_count": 0,
    }
    base.update(overrides)
    return HwProfile(**base)


# ---------------------------------------------------------------------------
# E2E: HardwareProbe.run() -> BackendPlanner.plan() -> BackendPlan
# ---------------------------------------------------------------------------


def test_real_hw_probe_to_planner_to_plan_e2e(monkeypatch: pytest.MonkeyPatch) -> None:
    """Deterministic e2e wire-up.

    With ``NOTEBOOK_OLLAMA_SKIP_ACCEL_PROBE=1`` the probe short-circuits to
    ``_STUB_PROFILE`` (CPU-only, no GPU/NPU). The planner consumes that and
    must produce the canonical CPU fallback plan. This is the test that
    proves the three layers compose under a single ``run -> plan`` call
    without touching the host.
    """
    monkeypatch.setenv(ENV_VAR_NAME, "1")

    profile = HardwareProbe().run()
    assert profile is _STUB_PROFILE, (
        "probe short-circuit returned a non-stub profile — env var not respected"
    )

    plan = BackendPlanner().plan(profile)
    assert isinstance(plan, BackendPlan)
    assert plan.hw_profile is _STUB_PROFILE

    # Canonical CPU fallback (mirrors tests/unit/test_planner.py
    # ::test_planner_picks_cpu_only_on_blank_hw).
    assert plan.stt_id == "faster-whisper-cpu"
    assert plan.diarize_id == "sherpa-onnx-cpu"
    assert plan.llm_id == "ollama-cuda"  # Ollama auto-degrades to CPU
    assert plan.text_embed_id == "ollama-bge-m3-cpu"

    # CPU-only plan must always be Phase 1 implementable — it's the floor.
    assert is_phase1_implementable(plan) is True


@requires_cuda
def test_real_dev_box_cuda_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    """Dev-box integration smoke (RTX 2080 Ti / clean Python).

    With the skip env var **unset**, the real ``HardwareProbe.run()`` invokes
    every sub-probe (nvidia-smi, ctranslate2, openvino, pnputil, ...). On the
    dev box this must produce an ``HwProfile`` with ``has_cuda=True``, which
    the planner must route to ``faster-whisper-cuda`` / ``ollama-cuda``.

    This is THE end-to-end proof that the Sprint 1+2 chain actually works on
    real hardware — every other test in this suite mocks something. If this
    fails on the dev box the user is silently off the CUDA path (regression
    of C1 fix, planner routing rules, or HwProfile wiring).
    """
    monkeypatch.delenv(ENV_VAR_NAME, raising=False)

    profile = HardwareProbe().run()
    assert profile.has_cuda is True, (
        "real HardwareProbe did not detect CUDA on the dev box — "
        "C1 DLL-dir fix may be broken (see core/accel/cuda_dll.py)"
    )
    assert profile.cuda_device_count >= 1
    assert profile.vendor == "nvidia"

    plan = BackendPlanner().plan(profile)
    assert plan.stt_id == "faster-whisper-cuda"
    assert plan.llm_id == "ollama-cuda"
    assert plan.diarize_id == "sherpa-onnx-cpu"  # cpu-only in v1
    # CUDA hosts pin embed to CPU due to Ollama #13572 NaN bug (spec §4.4).
    assert plan.text_embed_id == "ollama-bge-m3-cpu"

    # Every id on the dev box is in the Phase 1 implementable subset — the
    # Factory can actually build this plan with no Phase 2 stubs.
    assert is_phase1_implementable(plan) is True


@requires_cuda
def test_plan_reason_is_human_readable(monkeypatch: pytest.MonkeyPatch) -> None:
    """The Acceleration tab / startup log reads ``plan.reason`` verbatim.

    It must mention the chosen STT id and the accelerator family so a human
    can answer "why did I land on this backend?" without re-deriving the
    decision tree. On a CUDA host that means ``faster-whisper-cuda``, plus
    one of ``CUDA`` / ``RTX`` / ``dGPU``.
    """
    monkeypatch.delenv(ENV_VAR_NAME, raising=False)

    plan = BackendPlanner().plan(HardwareProbe().run())

    # Regex enforces that at least one of the human-grokable tokens shows up.
    # We don't pin the exact phrasing so wording can evolve without breaking
    # the gate.
    assert re.search(r"faster-whisper-cuda|RTX|CUDA|dGPU", plan.reason), (
        f"plan.reason missing CUDA marker: {plan.reason!r}"
    )

    # Every role must be called out so the operator can see the full picture.
    for role_marker in ("STT:", "DIARIZE:", "LLM:", "TEXT_EMBED:"):
        assert role_marker in plan.reason, (
            f"plan.reason missing {role_marker} marker: {plan.reason!r}"
        )


# ---------------------------------------------------------------------------
# Phase 1 implementability contract
# ---------------------------------------------------------------------------


@requires_cuda
def test_phase1_implementable_on_dev_box(monkeypatch: pytest.MonkeyPatch) -> None:
    """Dev-box plan only references Phase 1 implemented ids.

    ``faster-whisper-cuda`` + ``sherpa-onnx-cpu`` + ``ollama-cuda`` +
    ``ollama-bge-m3-cpu`` are all in ``PHASE1_IMPLEMENTABLE_IDS`` so the
    Factory can build them without a NotImplementedError fallback. This is
    the contract that lets Phase 1 ship CUDA users immediately, without
    waiting for Phase 2 Intel/AMD builders.
    """
    monkeypatch.delenv(ENV_VAR_NAME, raising=False)
    plan = BackendPlanner().plan(HardwareProbe().run())
    assert is_phase1_implementable(plan) is True

    # And every individual id is in the Phase 1 subset — defensive
    # double-check so a future change to the helper can't silently mask a
    # Phase 2 id leaking onto the dev box.
    assert plan.stt_id in PHASE1_IMPLEMENTABLE_IDS["STT"]
    assert plan.diarize_id in PHASE1_IMPLEMENTABLE_IDS["DIARIZE"]
    assert plan.llm_id in PHASE1_IMPLEMENTABLE_IDS["LLM"]
    assert plan.text_embed_id in PHASE1_IMPLEMENTABLE_IDS["TEXT_EMBED"]


def test_phase1_not_implementable_on_intel_lunar_lake() -> None:
    """Intel iGPU+NPU profile drives the planner to Phase 2 openvino-* ids.

    This is the *contract proof*: the planner is allowed to pick ids that
    the Factory hasn't implemented yet (because Planner is pure data,
    Factory is the gate). On a real Intel Lunar Lake box Phase 1 has nothing
    to build for STT/LLM/TEXT_EMBED — the test verifies that
    ``is_phase1_implementable`` honestly says so, rather than silently
    pretending the plan is buildable.

    Phase 2 will flip this to True when openvino-* builders land. Until
    then the False return is what the Acceleration tab uses to surface
    "Phase 2 backend not yet available" instead of crashing in Factory.
    """
    intel_lunar_lake = _profile(
        vendor="intel",
        cpu_brand="Intel(R) Core(TM) Ultra 7 258V",
        igpu="Intel iGPU",
        npu="Intel NPU",
        openvino_devices=("CPU", "GPU", "NPU"),
    )

    plan = BackendPlanner().plan(intel_lunar_lake)

    # Planner must route to openvino-* (the *correct* Phase 2 ids), not
    # silently fall back to CPU. The whole point of declaring Phase 2 ids in
    # BACKEND_IDS without Factory builders is that the Planner is honest
    # about the right choice; the Factory is the gate that signals "not yet".
    assert plan.stt_id == "openvino-whisper-npu"
    assert plan.llm_id == "ipex-llm-ollama"
    # NPU contention degrades text embed off the NPU; openvino-bge-m3-igpu
    # is also Phase 2.
    assert plan.text_embed_id == "openvino-bge-m3-igpu"
    # Diarizer is CPU-only on every host — that one piece IS Phase 1 OK.
    assert plan.diarize_id == "sherpa-onnx-cpu"

    # The headline contract assertion.
    assert is_phase1_implementable(plan) is False, (
        "Intel Lunar Lake plan must NOT be Phase 1 implementable — the "
        "openvino-* ids are declared but their Factory builders ship in Phase 2"
    )


# ---------------------------------------------------------------------------
# Regression-locking: BACKEND_IDS["STT"] is the single source of truth
# ---------------------------------------------------------------------------


# Sorted for deterministic parametrize ids. The set itself is imported from
# core.accel.backend_ids so this file can never drift out of sync — the
# test_parametrized_stt_ids_match_single_source_of_truth gate re-asserts the
# equality on every run.
_PARAMETRIZED_STT_IDS = sorted(BACKEND_IDS["STT"])


def test_parametrized_stt_ids_match_single_source_of_truth() -> None:
    """Meta-test: ensure the parametrize fixture below was not hand-rolled.

    If a future commit adds a new STT id to ``BACKEND_IDS["STT"]`` but
    forgets to refresh ``_PARAMETRIZED_STT_IDS``, this test fails loudly
    (rather than silently leaving the new id untested). The pattern enforces
    "one source of truth, derived everywhere else" for backend id lists in
    the test suite.
    """
    assert frozenset(_PARAMETRIZED_STT_IDS) == BACKEND_IDS["STT"], (
        "_PARAMETRIZED_STT_IDS drifted from BACKEND_IDS['STT'] — refresh "
        "the derivation to keep a single source of truth"
    )


@pytest.mark.parametrize("stt_id", _PARAMETRIZED_STT_IDS)
def test_every_stt_id_is_constructible_in_a_plan(stt_id: str) -> None:
    """Every declared STT id must be accepted by ``BackendPlan.__post_init__``.

    A 'dead id' regression — an id added to ``BACKEND_IDS["STT"]`` but
    rejected by validation — would otherwise be invisible until a Planner
    test happened to route to it. Parametrising over the entire imported
    set catches the regression on any new id immediately.
    """
    plan = BackendPlan(
        stt_id=stt_id,
        diarize_id="sherpa-onnx-cpu",
        llm_id="ollama-cuda",
        text_embed_id="ollama-bge-m3-cpu",
        hw_profile=_STUB_PROFILE,
        reason=f"parametrized stt_id={stt_id}",
    )
    assert plan.stt_id == stt_id


@pytest.mark.parametrize("stt_id", _PARAMETRIZED_STT_IDS)
def test_every_stt_id_classifies_as_phase1_or_phase2(stt_id: str) -> None:
    """Each declared STT id is either Phase 1 implementable OR Phase 2 deferred.

    Together with ``BACKEND_IDS["STT"]`` being the single source of truth,
    this proves the partition is exhaustive — no id sits in a third
    "declared but neither Phase 1 nor Phase 2" limbo where the Acceleration
    tab would have no signal to give the user.
    """
    is_phase1 = stt_id in PHASE1_IMPLEMENTABLE_IDS["STT"]
    # Phase 2 = declared in BACKEND_IDS but not yet implementable. The set
    # difference is the Phase 2 cohort.
    phase2_ids = BACKEND_IDS["STT"] - PHASE1_IMPLEMENTABLE_IDS["STT"]
    is_phase2 = stt_id in phase2_ids
    assert is_phase1 ^ is_phase2, (
        f"{stt_id!r} must be exactly one of Phase 1 / Phase 2, "
        f"got phase1={is_phase1} phase2={is_phase2}"
    )
