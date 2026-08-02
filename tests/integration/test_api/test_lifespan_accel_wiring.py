"""Sprint 3 / Task 3.4 — lifespan DI smoke for accel wiring.

Verifies that ``apps.api.dependencies.build_context`` + ``apps.api.main``
lifespan composes the Sprint 1 (``HardwareProbe``) and Sprint 2
(``BackendPlanner`` / ``BackendFactory``) layers into a usable
:class:`AppContext`:

* ``ctx.hw_profile`` / ``ctx.backend_plan`` / ``ctx.backend_factory`` are
  populated during lifespan startup (no on-demand probing at first
  request).
* ``ctx.transcriber`` resolves through ``ctx.backend_factory.build_transcriber``
  and yields a ``FasterWhisperTranscriber``-like instance — on the dev box
  that means a real ``Transcriber``; in this test mode the Factory is
  monkeypatched to return a lightweight fake so no faster-whisper model is
  loaded.
* ``ctx.ollama_gateway`` and ``ctx.text_embedder`` are pointed at the
  Factory-built instances; ``ctx.ollama`` (legacy attr) is preserved as
  the same object so downstream code paths stay unchanged.
* The lifespan emits a single structlog banner whose payload contains
  ``stt_id`` + the chosen ``llm_id`` (``ollama-cuda`` on every CUDA / CPU
  Phase 1 plan) so the operator can grep the startup log.

The autouse ``_skip_accel_probe_env`` fixture pins
``NOTEBOOK_OLLAMA_SKIP_ACCEL_PROBE=1`` so :func:`HardwareProbe.run` returns
``_STUB_PROFILE`` instead of shelling out to ``pnputil`` / ``nvidia-smi`` —
CI hosts (Linux, no NVIDIA) can run this test deterministically.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from apps.api.main import create_app
from core.accel.backend_ids import BACKEND_IDS
from core.accel.factory import BackendFactory, _OllamaTextEmbedder
from core.accel.plan import (
    PHASE1_IMPLEMENTABLE_IDS,
    BackendPlan,
    is_phase1_implementable,
)
from core.accel.profile import _STUB_PROFILE, HwProfile
from core.ollama.gateway import OllamaGateway

# ---------------------------------------------------------------------------
# Lightweight fakes (so the Factory-patched path stays I/O-free)
# ---------------------------------------------------------------------------


class _FakeFasterWhisperTranscriber:
    """Phase 1 test stub for the FasterWhisperTranscriber instance.

    The real ``Transcriber`` (``core.recording.transcriber.Transcriber``)
    constructor loads a multi-gigabyte WhisperModel via faster-whisper. We
    swap it out at the Factory boundary so the lifespan smoke runs in
    milliseconds without any GPU/CUDA dependency.
    """

    def transcribe(self, *args, **kwargs):  # pragma: no cover - never invoked
        raise NotImplementedError(
            "_FakeFasterWhisperTranscriber.transcribe must not be called "
            "from the lifespan smoke test"
        )


class _FakeSherpaDiarizer:
    """Phase 1 test stub for the SherpaDiarizer instance."""

    def diarize(self, *args, **kwargs):  # pragma: no cover - never invoked
        raise NotImplementedError(
            "_FakeSherpaDiarizer.diarize must not be called from the "
            "lifespan smoke test"
        )


# ---------------------------------------------------------------------------
# Autouse fixtures — patch the env + the heavy Factory builders
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _skip_accel_probe_env(monkeypatch):
    """Pin SKIP_ACCEL_PROBE=1 so the lifespan does not shell out to ``pnputil``.

    With the env var set, ``HardwareProbe.run()`` returns ``_STUB_PROFILE``
    (cpu-only) — the planner then picks the canonical Phase 1 CPU plan,
    which is what we assert on below.
    """
    monkeypatch.setenv("NOTEBOOK_OLLAMA_SKIP_ACCEL_PROBE", "1")


@pytest.fixture(autouse=True)
def _patch_backend_factory_builders(monkeypatch):
    """Replace ``BackendFactory.build_transcriber`` / ``build_diarizer`` with fakes.

    The Factory's real ``build_transcriber`` calls ``Transcriber(...)`` which
    loads faster-whisper. We bypass that with a no-op stub so the lifespan
    smoke executes the full DI chain (probe -> plan -> factory.build_*)
    without paying the WhisperModel load cost on every test run.

    ``build_llm_gateway`` and ``build_text_embedder`` are left UNPATCHED so
    the test exercises the real Factory wiring against the real
    ``OllamaGateway`` / ``_OllamaTextEmbedder`` constructors — those are
    cheap (no model load, just an httpx client).
    """
    monkeypatch.setattr(
        BackendFactory,
        "build_transcriber",
        lambda self, plan, audio_cfg: _FakeFasterWhisperTranscriber(),
    )
    monkeypatch.setattr(
        BackendFactory,
        "build_diarizer",
        lambda self, plan, audio_cfg: _FakeSherpaDiarizer(),
    )


@pytest.fixture
def client(tmp_path, monkeypatch, capfd):
    """Spin up an isolated app instance + capture the lifespan stderr output.

    ``capfd`` reads at the OS file-descriptor level so it captures the
    structlog ``PrintLoggerFactory`` output regardless of which ``sys.stderr``
    object the test runner has swapped in. Yields ``(client, capfd)`` so the
    individual tests can assert on the banner payload.
    """
    monkeypatch.setenv("NOTEBOOK_OLLAMA_DATA_DIR", str(tmp_path))
    app = create_app()
    with TestClient(app) as c:
        yield c, capfd


# ---------------------------------------------------------------------------
# Test surface
# ---------------------------------------------------------------------------


class TestAccelDIWiring:
    def test_hw_profile_is_set(self, client):
        c, _capfd = client
        ctx = c.app.state.ctx
        assert isinstance(ctx.hw_profile, HwProfile)
        # SKIP_ACCEL_PROBE=1 short-circuits to _STUB_PROFILE.
        assert ctx.hw_profile is _STUB_PROFILE
        # The stub is CPU-only by design — no GPU/NPU signals leak.
        assert ctx.hw_profile.has_cuda is False
        assert ctx.hw_profile.openvino_devices == ()

    def test_backend_plan_is_set_and_phase1_implementable(self, client):
        c, _capfd = client
        ctx = c.app.state.ctx
        assert isinstance(ctx.backend_plan, BackendPlan)
        # On the stub CPU-only profile the planner picks the canonical
        # Phase 1 CPU plan.
        assert ctx.backend_plan.stt_id == "faster-whisper-cpu"
        assert ctx.backend_plan.diarize_id == "sherpa-onnx-cpu"
        # ``ollama-cuda`` covers the CPU-only host too — Ollama auto-
        # degrades to CPU when no GPU is visible (Planner's documented
        # behaviour, asserted by tests/unit/test_planner.py as well).
        assert ctx.backend_plan.llm_id == "ollama-cuda"
        assert ctx.backend_plan.text_embed_id == "ollama-bge-m3-cpu"
        # Plan must be implementable by the Phase 1 Factory or build_context
        # would have degraded it; assert the contract directly.
        assert is_phase1_implementable(ctx.backend_plan)
        # Every chosen id is in the canonical BACKEND_IDS source-of-truth
        # AND in the PHASE1_IMPLEMENTABLE_IDS subset.
        assert ctx.backend_plan.stt_id in BACKEND_IDS["STT"]
        assert ctx.backend_plan.stt_id in PHASE1_IMPLEMENTABLE_IDS["STT"]
        assert ctx.backend_plan.llm_id in PHASE1_IMPLEMENTABLE_IDS["LLM"]

    def test_backend_factory_is_a_BackendFactory(self, client):
        c, _capfd = client
        ctx = c.app.state.ctx
        assert isinstance(ctx.backend_factory, BackendFactory)

    def test_transcriber_is_factory_built_fake_in_test_mode(self, client):
        """``ctx.transcriber`` is the lazy property — first access builds via Factory.

        On the dev box (RTX 2080 Ti), with the autouse Factory patch
        REMOVED, this would resolve to a real ``Transcriber`` constructed
        with ``model_size=large-v3 / device=cuda / compute_type=float16`` —
        bit-identical to the pre-Sprint-3 lazy construction in
        ``recordings.py::_get_transcriber``. Here we assert on the fake
        because the autouse fixture replaced the Factory builder.
        """
        c, _capfd = client
        ctx = c.app.state.ctx
        tr = ctx.transcriber
        assert isinstance(tr, _FakeFasterWhisperTranscriber)
        # Cached — second access returns the same instance, no re-build.
        assert ctx.transcriber is tr

    def test_diarizer_is_none_when_models_absent(self, client):
        """``ctx.diarizer`` returns None when the ONNX model files are missing.

        The graceful-degradation contract: when sherpa-onnx model weights
        aren't on disk yet, the offline pipeline must keep running in
        single-speaker mode rather than crashing. ``tmp_path`` (used as
        ``NOTEBOOK_OLLAMA_DATA_DIR``) has no ``models/`` subdir, so
        ``ctx.diarizer`` must resolve to None.
        """
        c, _capfd = client
        ctx = c.app.state.ctx
        assert ctx.diarizer is None
        # Second access uses the cached resolution result (not re-checked).
        assert ctx.diarizer is None

    def test_ollama_gateway_aliases_ctx_ollama(self, client):
        """``ctx.ollama_gateway`` and the legacy ``ctx.ollama`` point at the same
        instance so downstream call sites (ingestion / retrieval / generation /
        recording_pipeline) don't double-open httpx clients.
        """
        c, _capfd = client
        ctx = c.app.state.ctx
        assert isinstance(ctx.ollama_gateway, OllamaGateway)
        assert ctx.ollama is ctx.ollama_gateway

    def test_text_embedder_is_OllamaTextEmbedder_bound_to_embedding_model(
        self, client
    ):
        """``ctx.text_embedder`` is the Factory-built ``_OllamaTextEmbedder``
        bound to ``config.ollama.embedding_model`` ("bge-m3" by default).
        """
        c, _capfd = client
        ctx = c.app.state.ctx
        assert isinstance(ctx.text_embedder, _OllamaTextEmbedder)
        assert ctx.text_embedder.model == ctx.config.ollama.embedding_model


class TestDegradeOnPhase2Plan:
    """Sprint 3 / Task 3.4 — degrade-to-CPU when Planner picks a Phase 2 plan.

    On hosts where the Planner routes to a plan containing Phase-2-only ids
    (e.g. Intel Lunar Lake: ``openvino-whisper-npu`` +
    ``openvino-bge-m3-igpu``; the LLM id ``ollama-vulkan`` itself is
    Phase 1.5 implementable), the Factory cannot build the chosen ids. The
    lifespan must NOT crash — instead it warns and degrades to a CPU-only
    plan that is guaranteed implementable (``faster-whisper-cpu`` +
    ``sherpa-onnx-cpu`` + ``ollama-cuda`` + ``ollama-bge-m3-cpu``).

    This test pins the degrade behaviour (vs alternative: raise startup
    error) and the warning-banner contract so a future refactor cannot
    silently swap one for the other.
    """

    def test_phase2_plan_degrades_to_cpu_and_warns(
        self, tmp_path, monkeypatch, capfd
    ):
        """Intel Lunar Lake profile → Phase 2 plan → degrade + warn."""
        # Synthetic Intel Lunar Lake profile. OpenVINO exposes CPU/GPU/NPU so
        # the Planner picks:
        #   STT          = openvino-whisper-npu   (NPU + iGPU rule)
        #   DIARIZE      = sherpa-onnx-cpu        (cpu-only always)
        #   LLM          = ollama-vulkan          (iGPU rule, addendum K1)
        #   TEXT_EMBED   = openvino-bge-m3-igpu   (NPU contention → iGPU)
        # — STT / TEXT_EMBED are Phase 2, so is_phase1_implementable is False.
        lunar_lake = HwProfile(
            vendor="intel",
            cpu_brand="Intel Core Ultra 7 268V (Lunar Lake)",
            dgpu=None,
            igpu="Intel Arc Xe2 (140V)",
            npu="NPU 4",
            vram_mb=None,
            ryzen_ai_gen=None,
            openvino_devices=("CPU", "GPU", "NPU"),
            has_directml=False,
            has_cuda=False,
            cuda_device_count=0,
        )

        # Patch HardwareProbe.run directly so the synthetic profile feeds the
        # planner regardless of the autouse SKIP_ACCEL_PROBE env (which would
        # otherwise route to _STUB_PROFILE and pick a Phase 1 CPU plan).
        from core.accel.probe import HardwareProbe
        monkeypatch.setattr(HardwareProbe, "run", lambda self: lunar_lake)
        monkeypatch.setenv("NOTEBOOK_OLLAMA_DATA_DIR", str(tmp_path))

        app = create_app()
        with TestClient(app) as _c:
            captured = capfd.readouterr()
            ctx = app.state.ctx

        # 1. Warning banner emitted with the pre-degrade Phase 2 ids so
        #    operators can grep for the trigger.
        warn_lines = [
            line
            for line in (captured.err or "").splitlines()
            if "backend_plan_not_phase1_implementable" in line
        ]
        assert warn_lines, (
            "lifespan must warn when Planner picks a Phase 2 plan; "
            f"captured stderr: {captured.err!r}"
        )
        record = json.loads(warn_lines[0])
        assert record["event"] == "backend_plan_not_phase1_implementable"
        # The structlog ``add_log_level`` processor records the warn level
        # so log aggregators can filter on severity.
        assert record["level"] == "warning"
        # Pre-degrade Phase 2 ids appear in the warning payload — pinned so
        # a future refactor cannot silently drop them.
        assert record["stt_id"] == "openvino-whisper-npu"
        assert record["llm_id"] == "ollama-vulkan"
        assert record["text_embed_id"] == "openvino-bge-m3-igpu"
        # ``action="degrade_to_cpu_plan"`` is the locked behaviour (alt:
        # raise startup error). Test docs the choice + the bridge to
        # dependencies.py.
        assert record["action"] == "degrade_to_cpu_plan"

        # 2. The resulting AppContext carries the degraded CPU plan, not
        #    the original Phase 2 plan.
        assert isinstance(ctx.backend_plan, BackendPlan)
        assert is_phase1_implementable(ctx.backend_plan)
        assert ctx.backend_plan.stt_id == "faster-whisper-cpu"
        assert ctx.backend_plan.diarize_id == "sherpa-onnx-cpu"
        # ``ollama-cuda`` covers the CPU host too — Ollama auto-degrades
        # to CPU when no GPU is visible.
        assert ctx.backend_plan.llm_id == "ollama-cuda"
        assert ctx.backend_plan.text_embed_id == "ollama-bge-m3-cpu"
        # The original probe-derived HwProfile is preserved so the
        # Acceleration tab can still display the host's real capability set
        # alongside the "Phase 1 only ships CPU" diagnostic.
        assert ctx.hw_profile is lunar_lake


class TestTextEmbedderGatewayReuse:
    """Lifespan DI must keep a single ``OllamaGateway`` per process.

    ``ctx.text_embedder`` is the Factory-built ``_OllamaTextEmbedder``; per
    Sprint 3 / Task 3.4 it must reuse ``ctx.ollama_gateway`` (the LLM gateway)
    rather than open a second httpx client. The Factory enforces this via the
    ``gateway=`` kwarg; ``apps.api.dependencies.build_context`` passes
    ``ctx.ollama_gateway`` through.
    """

    def test_text_embedder_gateway_is_same_instance_as_ctx_ollama(self, client):
        c, _capfd = client
        ctx = c.app.state.ctx
        assert ctx.text_embedder.gateway is ctx.ollama_gateway


class TestLifespanBanner:
    def test_banner_logged_with_plan_ids(self, client):
        """Lifespan emits a single structlog banner whose payload carries
        ``stt_id`` + ``llm_id`` so the chosen plan is visible in startup logs.

        ``ollama-cuda`` is the Phase 1 LLM id on every host (CUDA hosts use
        the real GPU; CPU-only hosts ride the Ollama-auto-degrades-to-CPU
        path) — the assertion below pins both substrings since the spec
        explicitly calls them out.
        """
        _c, capfd_ = client
        captured = capfd_.readouterr()
        # The structlog PrintLoggerFactory writes JSON lines to stderr.
        # We look for the banner event line specifically.
        banner_lines = [
            line
            for line in (captured.err or "").splitlines()
            if "backend_plan_resolved" in line
        ]
        assert banner_lines, (
            "lifespan must emit a 'backend_plan_resolved' banner; "
            f"captured stderr: {captured.err!r}"
        )
        # Parse the first banner line — it must be valid JSON with the
        # documented keys.
        try:
            record = json.loads(banner_lines[0])
        except json.JSONDecodeError as exc:
            pytest.fail(
                f"banner line not valid JSON: {banner_lines[0]!r} ({exc})"
            )
        assert record["event"] == "backend_plan_resolved"
        # The two anchors the spec calls out.
        assert "stt_id" in record
        assert record["llm_id"] == "ollama-cuda"
        # Plus the rest of the plan ids — pinned so a future refactor
        # cannot silently drop them from the banner.
        assert record["diarize_id"] == "sherpa-onnx-cpu"
        assert record["text_embed_id"] == "ollama-bge-m3-cpu"
        # And the HwProfile shape — vendor + cpu_brand are the minimum
        # operator-facing diagnostic.
        assert "vendor" in record
        assert "cpu_brand" in record
