"""Sprint 2 / Task 2.2 — ``BackendPlanner.plan()`` routing rules.

Table-driven verification of the planner's per-role selection across every
HW profile combination relevant to v1:

* CUDA dGPU (RTX 2080 Ti) — AC-CUDA-REGRESSION baseline.
* Intel Meteor / Lunar / Arrow Lake (iGPU + NPU; iGPU-only).
* AMD Phoenix / Hawk Point / Strix / Krackan Point (NPU + DirectML).
* CPU-only.

The planner is a pure function of an ``HwProfile``: no probes are invoked
and no ``HardwareProbe`` import is needed. All fixtures are constructed
in-line via the ``_profile`` helper.

User-decision guard tests (``test_*_rejected_in_v1``) re-verify the
``BackendPlan`` constructor's validation gate (Task 2.1) so that a future
regression that re-introduces a dropped id surfaces in *this* file too,
not only in ``test_backend_plan.py``.
"""

from __future__ import annotations

from typing import Any

import pytest

from core.accel.plan import BackendPlan
from core.accel.planner import BackendPlanner
from core.accel.profile import _STUB_PROFILE, HwProfile

# ---------------------------------------------------------------------------
# HwProfile fixture helpers
# ---------------------------------------------------------------------------


def _profile(**overrides: Any) -> HwProfile:
    """Construct an ``HwProfile`` with sane CPU-only defaults.

    Any field can be overridden via kwargs. Mirrors the convention used in
    ``test_backend_plan.py`` so the two test modules stay readable side by
    side.
    """
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


# Canonical HW profiles used across the parametrized sweeps below.

_CUDA_PROFILE: HwProfile = _profile(
    vendor="nvidia",
    cpu_brand="12th Gen Intel(R) Core(TM) i9-12900KF",
    dgpu="NVIDIA GeForce RTX 2080 Ti",
    vram_mb=11264,
    has_cuda=True,
    cuda_device_count=1,
)

_INTEL_METEOR: HwProfile = _profile(
    vendor="intel",
    cpu_brand="Intel(R) Core(TM) Ultra 7 155H",
    igpu="Intel iGPU",
    npu="Intel NPU",
    openvino_devices=("CPU", "GPU", "NPU"),
)

_INTEL_LUNAR: HwProfile = _profile(
    vendor="intel",
    cpu_brand="Intel(R) Core(TM) Ultra 7 258V",
    igpu="Intel iGPU",
    npu="Intel NPU",
    openvino_devices=("CPU", "GPU", "NPU"),
)

_INTEL_ARROW: HwProfile = _profile(
    vendor="intel",
    cpu_brand="Intel(R) Core(TM) Ultra 9 285K",
    igpu="Intel iGPU",
    npu="Intel NPU",
    openvino_devices=("CPU", "GPU", "NPU"),
)

_AMD_PHOENIX: HwProfile = _profile(
    vendor="amd",
    cpu_brand="AMD Ryzen 7 7840U",
    npu="phoenix",
    ryzen_ai_gen=1,
    has_directml=True,
)

_AMD_STRIX: HwProfile = _profile(
    vendor="amd",
    cpu_brand="AMD Ryzen AI 9 HX 370",
    npu="strix",
    ryzen_ai_gen=2,
    has_directml=True,
)

_AMD_KRACKAN: HwProfile = _profile(
    vendor="amd",
    cpu_brand="AMD Ryzen AI 7 350",
    npu="krackan_point",
    ryzen_ai_gen=2,
    has_directml=True,
)

# All 8 HW profiles used by the "sherpa-onnx-cpu on every host" sweep.
_ALL_HW_PROFILES: list[tuple[str, HwProfile]] = [
    ("cuda", _CUDA_PROFILE),
    ("intel-meteor", _INTEL_METEOR),
    ("intel-lunar", _INTEL_LUNAR),
    ("intel-arrow", _INTEL_ARROW),
    ("amd-phoenix", _AMD_PHOENIX),
    ("amd-strix", _AMD_STRIX),
    ("amd-krackan", _AMD_KRACKAN),
    ("cpu-only", _STUB_PROFILE),
]


# ---------------------------------------------------------------------------
# CUDA dGPU baseline (AC-CUDA-REGRESSION)
# ---------------------------------------------------------------------------


def test_planner_picks_cuda_on_rtx_2080ti() -> None:
    """Dev-machine baseline: RTX 2080 Ti routes to the CUDA backends.

    This is the AC-CUDA-REGRESSION acceptance test for Phase 1 — if this
    breaks the dev machine has silently fallen off the CUDA path.
    """
    plan = BackendPlanner().plan(_CUDA_PROFILE)

    assert plan.stt_id == "faster-whisper-cuda"
    assert plan.diarize_id == "sherpa-onnx-cpu"
    assert plan.llm_id == "ollama-cuda"
    assert plan.text_embed_id == "ollama-bge-m3-cpu"
    assert plan.hw_profile is _CUDA_PROFILE
    assert "faster-whisper-cuda" in plan.reason
    assert "ollama-cuda" in plan.reason


# ---------------------------------------------------------------------------
# CPU-only fallback (stub profile)
# ---------------------------------------------------------------------------


def test_planner_picks_cpu_only_on_blank_hw() -> None:
    """``_STUB_PROFILE`` is the canonical CPU-only host — every role degrades
    to its CPU backend (LLM picks ``ollama-cuda`` because Ollama auto-degrades
    to CPU when no GPU is visible)."""
    plan = BackendPlanner().plan(_STUB_PROFILE)

    assert plan.stt_id == "faster-whisper-cpu"
    assert plan.diarize_id == "sherpa-onnx-cpu"
    assert plan.llm_id == "ollama-cuda"
    assert plan.text_embed_id == "ollama-bge-m3-cpu"
    assert plan.hw_profile is _STUB_PROFILE


# ---------------------------------------------------------------------------
# Intel iGPU / NPU routing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,hw",
    [
        ("intel-meteor", _INTEL_METEOR),
        ("intel-lunar", _INTEL_LUNAR),
        ("intel-arrow", _INTEL_ARROW),
    ],
)
def test_planner_intel_npu_picks_openvino_whisper_npu(
    name: str, hw: HwProfile
) -> None:
    """Intel iGPU + NPU hosts route STT to ``openvino-whisper-npu``.

    LLM routes to ``ollama-vulkan`` (addendum K1/K2: ipex-llm-ollama dropped
    for security issues; official Ollama Vulkan backend covers Intel iGPU).
    """
    del name
    plan = BackendPlanner().plan(hw)
    assert plan.stt_id == "openvino-whisper-npu"
    assert plan.llm_id == "ollama-vulkan"


def test_planner_intel_igpu_only_picks_openvino_whisper_igpu() -> None:
    """Intel iGPU without NPU routes STT to ``openvino-whisper-igpu`` and
    TEXT_EMBED to ``openvino-bge-m3-igpu``."""
    hw = _profile(
        vendor="intel",
        igpu="Intel iGPU",
        openvino_devices=("CPU", "GPU"),
    )
    plan = BackendPlanner().plan(hw)
    assert plan.stt_id == "openvino-whisper-igpu"
    assert plan.llm_id == "ollama-vulkan"
    assert plan.text_embed_id == "openvino-bge-m3-igpu"


# ---------------------------------------------------------------------------
# NPU contention (spec §6.3): STT wins, TEXT_EMBED degrades
# ---------------------------------------------------------------------------


def test_planner_npu_contention_prefers_stt() -> None:
    """When STT picks an NPU backend, TEXT_EMBED must degrade off the NPU.

    Spec §6.3: NPU is a single-process resource. STT is real-time and
    keeps the NPU; TEXT_EMBED falls back to iGPU (or CPU when no iGPU).
    """
    hw = _INTEL_METEOR  # iGPU + NPU
    plan = BackendPlanner().plan(hw)

    # STT keeps the NPU.
    assert plan.stt_id == "openvino-whisper-npu"
    # TEXT_EMBED degrades to the iGPU variant — NOT openvino-bge-m3-npu.
    assert plan.text_embed_id == "openvino-bge-m3-igpu"
    assert plan.text_embed_id != "openvino-bge-m3-npu"


def test_planner_npu_contention_degrades_to_cpu_when_no_igpu() -> None:
    """If the host has NPU but no iGPU (synthetic), TEXT_EMBED degrades all
    the way to CPU rather than landing on a non-existent iGPU backend."""
    hw = _profile(
        vendor="intel",
        npu="Intel NPU",
        openvino_devices=("CPU", "NPU"),  # NPU only, no GPU
    )
    plan = BackendPlanner().plan(hw)
    # NPU-only (no iGPU) on Intel: STT cannot pick openvino-whisper-npu
    # because the planner gates that branch on iGPU + NPU coexisting (Intel
    # NPU drivers historically require the iGPU runtime). STT therefore
    # falls back to CPU and TEXT_EMBED follows to CPU as well — no NPU
    # contention occurs in this degenerate profile.
    assert plan.stt_id == "faster-whisper-cpu"
    assert plan.text_embed_id == "ollama-bge-m3-cpu"


# ---------------------------------------------------------------------------
# AMD Ryzen AI: NPU never picked for STT (dropped from BACKEND_IDS)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "chip,gen",
    [
        ("phoenix", 1),
        ("hawk_point", 1),
        ("strix", 2),
        ("krackan_point", 2),
    ],
)
def test_planner_amd_npu_never_picked_for_stt(chip: str, gen: int) -> None:
    """All 4 Ryzen AI chip families route STT to ``amd-whispercpp-vulkan``.

    User decision (captured in ``BACKEND_IDS``): ``amd-whispercpp-npu`` is
    permanently dropped. Addendum 2026-08-02: the AMD STT path rides Vulkan
    (whisper.cpp has no DirectML backend) and the LLM path is the official
    Ollama Vulkan backend (ROCm does not support Windows APUs).
    """
    hw = _profile(
        vendor="amd",
        cpu_brand=f"AMD Ryzen AI ({chip})",
        npu=chip,
        ryzen_ai_gen=gen,
        has_directml=True,
    )
    plan = BackendPlanner().plan(hw)

    assert plan.stt_id == "amd-whispercpp-vulkan"
    assert plan.stt_id != "amd-whispercpp-npu"
    assert plan.llm_id == "ollama-vulkan"


def test_planner_amd_without_directml_falls_back_to_cpu() -> None:
    """AMD host without DirectML (driver missing) degrades to CPU STT."""
    hw = _profile(
        vendor="amd",
        cpu_brand="AMD Ryzen 7 7840U",
        npu="phoenix",
        ryzen_ai_gen=1,
        has_directml=False,
    )
    plan = BackendPlanner().plan(hw)
    assert plan.stt_id == "faster-whisper-cpu"


# ---------------------------------------------------------------------------
# Diarize is always sherpa-onnx-cpu (all 8 HW profiles)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name,hw", _ALL_HW_PROFILES)
def test_planner_sherpa_dml_never_picked(name: str, hw: HwProfile) -> None:
    """Diarize is ``sherpa-onnx-cpu`` on EVERY HW profile in v1+v2.

    User decision: sherpa-onnx GPU/NPU variants (``sherpa-onnx-dml`` /
    ``sherpa-onnx-openvino-gpu`` / ``sherpa-onnx-openvino-npu``) are dropped
    from ``BACKEND_IDS["DIARIZE"]``. The planner must never emit them on any
    host, regardless of which GPU/NPU is present.
    """
    del name
    plan = BackendPlanner().plan(hw)
    assert plan.diarize_id == "sherpa-onnx-cpu"


# ---------------------------------------------------------------------------
# Dropped-id rejection (Task 2.1 validation gate, re-verified)
# ---------------------------------------------------------------------------


def test_amd_npu_override_rejected_in_v1() -> None:
    """``BackendPlan(stt_id="amd-whispercpp-npu", ...)`` raises ``ValueError``.

    The dropped id cannot sneak in through the constructor — covered by Task
    2.1's ``BackendPlan.__post_init__`` validation. Re-verified here so a
    regression in the planner module's neighborhood surfaces in
    ``test_planner.py`` too.
    """
    with pytest.raises(ValueError, match="unknown backend id"):
        BackendPlan(
            stt_id="amd-whispercpp-npu",
            diarize_id="sherpa-onnx-cpu",
            llm_id="ollama-cuda",
            text_embed_id="ollama-bge-m3-cpu",
            hw_profile=_CUDA_PROFILE,
            reason="dropped amd npu id (should never be constructed)",
        )


def test_sherpa_dml_override_rejected_in_v1() -> None:
    """``BackendPlan(diarize_id="sherpa-onnx-dml", ...)`` raises ``ValueError``."""
    with pytest.raises(ValueError, match="unknown backend id"):
        BackendPlan(
            stt_id="faster-whisper-cuda",
            diarize_id="sherpa-onnx-dml",
            llm_id="ollama-cuda",
            text_embed_id="ollama-bge-m3-cpu",
            hw_profile=_CUDA_PROFILE,
            reason="dropped sherpa dml id (should never be constructed)",
        )


# ---------------------------------------------------------------------------
# Reason string sanity (per-role explanation)
# ---------------------------------------------------------------------------


def test_planner_reason_mentions_every_role() -> None:
    """``BackendPlan.reason`` carries a 1-sentence explanation per role."""
    plan = BackendPlanner().plan(_CUDA_PROFILE)
    for role_marker in ("STT:", "DIARIZE:", "LLM:", "TEXT_EMBED:"):
        assert role_marker in plan.reason


def test_planner_npu_contention_reason_explains_degrade() -> None:
    """When NPU contention triggers, the reason string says so."""
    plan = BackendPlanner().plan(_INTEL_METEOR)
    assert "NPU contention" in plan.reason


# ---------------------------------------------------------------------------
# openai-compat is never auto-selected (addendum L)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name,hw", _ALL_HW_PROFILES)
def test_planner_never_auto_selects_openai_compat(name: str, hw: HwProfile) -> None:
    """``openai-compat`` / ``openai-compat-embed`` require an explicit user
    override — automatic detection cannot know an OpenAI-compatible server
    exists, let alone its URL."""
    del name
    plan = BackendPlanner().plan(hw)
    assert plan.llm_id != "openai-compat"
    assert plan.text_embed_id != "openai-compat-embed"


# ---------------------------------------------------------------------------
# User overrides (spec §5.1 step 5 / addendum M — Phase 1.5)
# ---------------------------------------------------------------------------


def test_override_auto_everywhere_matches_pure_auto_plan() -> None:
    """All-"auto" overrides (the addendum-H default) must be a no-op."""
    from core.accel.planner import BackendOverrides

    auto_plan = BackendPlanner().plan(_CUDA_PROFILE)
    ov_plan = BackendPlanner().plan(_CUDA_PROFILE, BackendOverrides())
    assert ov_plan.stt_id == auto_plan.stt_id
    assert ov_plan.diarize_id == auto_plan.diarize_id
    assert ov_plan.llm_id == auto_plan.llm_id
    assert ov_plan.text_embed_id == auto_plan.text_embed_id


def test_override_forces_openai_compat_llm() -> None:
    """runtime_backend="openai-compat" wins over the CUDA auto-pick."""
    from core.accel.planner import BackendOverrides

    plan = BackendPlanner().plan(
        _CUDA_PROFILE, BackendOverrides(llm="openai-compat")
    )
    assert plan.llm_id == "openai-compat"
    assert "user override" in plan.reason
    # 他ロールは auto のまま
    assert plan.stt_id == "faster-whisper-cuda"
    assert plan.text_embed_id == "ollama-bge-m3-cpu"


def test_override_forces_openai_compat_embed_independently() -> None:
    """text_embed_backend="openai-compat-embed" leaves the LLM on Ollama —
    the asymmetric wiring of addendum M(生成と埋め込みの独立エンドポイント)."""
    from core.accel.planner import BackendOverrides

    plan = BackendPlanner().plan(
        _CUDA_PROFILE, BackendOverrides(text_embed="openai-compat-embed")
    )
    assert plan.llm_id == "ollama-cuda"
    assert plan.text_embed_id == "openai-compat-embed"


def test_override_forces_cpu_stt_on_cuda_host() -> None:
    """transcriber_backend="faster-whisper-cpu" downgrades STT by choice."""
    from core.accel.planner import BackendOverrides

    plan = BackendPlanner().plan(
        _CUDA_PROFILE, BackendOverrides(stt="faster-whisper-cpu")
    )
    assert plan.stt_id == "faster-whisper-cpu"


def test_override_cpu_stt_frees_npu_for_embed() -> None:
    """STT override は NPU contention 判定より先に適用される。

    Intel iGPU+NPU ホストで transcriber_backend="faster-whisper-cpu" を強制
    すると STT は NPU を使わないため、TEXT_EMBED は contention 降格せず
    openvino-bge-m3-npu を選べる(/code-review 指摘の修正、2026-08-02)。
    """
    from core.accel.planner import BackendOverrides

    plan = BackendPlanner().plan(
        _INTEL_METEOR, BackendOverrides(stt="faster-whisper-cpu")
    )
    assert plan.stt_id == "faster-whisper-cpu"
    assert plan.text_embed_id == "openvino-bge-m3-npu"
    assert "NPU contention" not in plan.reason


def test_override_invalid_id_raises_value_error() -> None:
    """An unknown forced id is rejected by BackendPlan validation — the
    planner never emits a silently-wrong plan."""
    from core.accel.planner import BackendOverrides

    with pytest.raises(ValueError, match="unknown backend id"):
        BackendPlanner().plan(
            _CUDA_PROFILE, BackendOverrides(llm="ipex-llm-ollama")
        )
