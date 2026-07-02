"""Sprint 3 / Task 3.5 — GET /api/settings/acceleration.

Read-only endpoint that exposes the resolved ``HwProfile`` + ``BackendPlan``
the lifespan computed at startup. Phase 1 contract:

* Returns 200 with the documented JSON shape.
* No probing happens per-request — the response is a serialization of
  ``ctx.hw_profile`` and ``ctx.backend_plan`` (set by ``build_context``).
* The autouse ``_skip_accel_probe_env`` fixture pins
  ``NOTEBOOK_OLLAMA_SKIP_ACCEL_PROBE=1`` so :func:`HardwareProbe.run` returns
  the deterministic ``_STUB_PROFILE`` instead of shelling out to ``pnputil`` /
  ``nvidia-smi``.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from apps.api.main import create_app
from core.accel.profile import _STUB_PROFILE

# ---------------------------------------------------------------------------
# Autouse fixtures — pin SKIP_ACCEL_PROBE so the lifespan probes deterministically
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _skip_accel_probe_env(monkeypatch):
    """Pin SKIP_ACCEL_PROBE=1 so the response is deterministic on every host."""
    monkeypatch.setenv("NOTEBOOK_OLLAMA_SKIP_ACCEL_PROBE", "1")


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTEBOOK_OLLAMA_DATA_DIR", str(tmp_path))
    app = create_app()
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# Top-level shape
# ---------------------------------------------------------------------------


class TestAccelerationEndpointShape:
    def test_returns_200_and_top_level_keys(self, client):
        r = client.get("/api/settings/acceleration")
        assert r.status_code == 200
        body = r.json()
        assert set(body.keys()) == {
            "hw_profile",
            "backend_plan",
            "is_phase1_implementable",
        }

    def test_hw_profile_subkeys(self, client):
        r = client.get("/api/settings/acceleration")
        hw = r.json()["hw_profile"]
        # Canonical Phase 1 field set per spec §A.
        assert set(hw.keys()) == {
            "cpu_brand",
            "cuda",
            "dgpu",
            "igpu",
            "npu",
            "vram_mb",
            "ryzen_ai_gen",
            "openvino_devices",
            "has_directml",
        }

    def test_backend_plan_subkeys(self, client):
        r = client.get("/api/settings/acceleration")
        plan = r.json()["backend_plan"]
        assert set(plan.keys()) == {
            "stt_id",
            "diarize_id",
            "llm_id",
            "text_embed_id",
            "reason",
        }


# ---------------------------------------------------------------------------
# Field-by-field serialization against _STUB_PROFILE
# ---------------------------------------------------------------------------


class TestHwProfileSerialization:
    """Parametrize over each HwProfile field to assert it is serialized correctly.

    With SKIP_ACCEL_PROBE=1 the probe returns ``_STUB_PROFILE`` — a CPU-only
    machine with no GPU/NPU acceleration. The endpoint must echo each field
    of that stub verbatim (with the rename: ``has_cuda`` -> ``cuda``).
    """

    @pytest.mark.parametrize(
        "field,expected",
        [
            ("cpu_brand", _STUB_PROFILE.cpu_brand),
            ("dgpu", _STUB_PROFILE.dgpu),
            ("igpu", _STUB_PROFILE.igpu),
            ("npu", _STUB_PROFILE.npu),
            ("vram_mb", _STUB_PROFILE.vram_mb),
            ("ryzen_ai_gen", _STUB_PROFILE.ryzen_ai_gen),
            ("has_directml", _STUB_PROFILE.has_directml),
        ],
    )
    def test_scalar_fields(self, client, field, expected):
        r = client.get("/api/settings/acceleration")
        hw = r.json()["hw_profile"]
        assert hw[field] == expected

    def test_cuda_is_renamed_from_has_cuda(self, client):
        """``has_cuda`` in HwProfile -> ``cuda`` in JSON per task spec."""
        r = client.get("/api/settings/acceleration")
        hw = r.json()["hw_profile"]
        assert hw["cuda"] == _STUB_PROFILE.has_cuda
        # Negative: original field name should NOT leak through.
        assert "has_cuda" not in hw

    def test_openvino_devices_is_list(self, client):
        """``openvino_devices`` is a tuple in HwProfile but JSON cannot
        represent tuples natively — must serialize as a list (empty tuple
        -> empty list)."""
        r = client.get("/api/settings/acceleration")
        hw = r.json()["hw_profile"]
        assert hw["openvino_devices"] == list(_STUB_PROFILE.openvino_devices)
        assert isinstance(hw["openvino_devices"], list)


# ---------------------------------------------------------------------------
# Backend plan + Phase 1 gate
# ---------------------------------------------------------------------------


class TestBackendPlanSerialization:
    def test_plan_ids_on_stub_profile(self, client):
        """On the CPU-only stub, the planner picks the canonical CPU plan."""
        r = client.get("/api/settings/acceleration")
        plan = r.json()["backend_plan"]
        assert plan["stt_id"] == "faster-whisper-cpu"
        assert plan["diarize_id"] == "sherpa-onnx-cpu"
        # Ollama LLM id covers CPU-only too (auto-degrades).
        assert plan["llm_id"] == "ollama-cuda"
        assert plan["text_embed_id"] == "ollama-bge-m3-cpu"

    def test_reason_is_non_empty_string(self, client):
        r = client.get("/api/settings/acceleration")
        plan = r.json()["backend_plan"]
        assert isinstance(plan["reason"], str)
        assert plan["reason"]


class TestPhase1ImplementabilityGate:
    def test_stub_profile_plan_is_phase1_implementable(self, client):
        """The CPU plan picked for ``_STUB_PROFILE`` is fully buildable in Phase 1."""
        r = client.get("/api/settings/acceleration")
        body = r.json()
        assert body["is_phase1_implementable"] is True

    def test_is_phase1_implementable_is_boolean(self, client):
        r = client.get("/api/settings/acceleration")
        body = r.json()
        assert isinstance(body["is_phase1_implementable"], bool)
