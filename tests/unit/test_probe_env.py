"""Tests for `core.accel.probe_env.should_skip_probe` and `_STUB_PROFILE`.

Covers Task 1.2 of the Phase 1 iGPU/NPU acceleration plan.
"""

from __future__ import annotations

import pytest

from core.accel import _STUB_PROFILE, HwProfile
from core.accel.probe_env import ENV_VAR_NAME, should_skip_probe


class TestShouldSkipProbe:
    """Only the exact string '1' counts — every other value is False."""

    def test_returns_false_when_env_var_unset(self, monkeypatch):
        monkeypatch.delenv(ENV_VAR_NAME, raising=False)
        assert should_skip_probe() is False

    @pytest.mark.parametrize(
        "value,expected",
        [
            ("", False),
            ("0", False),
            ("1", True),
            ("true", False),
            ("True", False),
            ("TRUE", False),
            ("yes", False),
            ("on", False),
            ("2", False),
            (" 1", False),
            ("1 ", False),
            ("01", False),
        ],
    )
    def test_parametrized_env_values(self, monkeypatch, value, expected):
        monkeypatch.setenv(ENV_VAR_NAME, value)
        assert should_skip_probe() is expected

    def test_env_var_name_is_the_documented_constant(self):
        assert ENV_VAR_NAME == "NOTEBOOK_OLLAMA_SKIP_ACCEL_PROBE"


class TestStubProfile:
    """`_STUB_PROFILE` represents a CPU-only machine with no accelerators."""

    def test_stub_profile_is_an_hwprofile(self):
        assert isinstance(_STUB_PROFILE, HwProfile)

    def test_stub_profile_field_values(self):
        assert _STUB_PROFILE.cpu_brand == "test"
        assert _STUB_PROFILE.dgpu is None
        assert _STUB_PROFILE.igpu is None
        assert _STUB_PROFILE.npu is None
        assert _STUB_PROFILE.vram_mb is None
        assert _STUB_PROFILE.ryzen_ai_gen is None
        assert _STUB_PROFILE.openvino_devices == ()
        assert _STUB_PROFILE.has_directml is False
        assert _STUB_PROFILE.has_cuda is False
        assert _STUB_PROFILE.cuda_device_count == 0

    def test_stub_profile_is_frozen(self):
        with pytest.raises(Exception):  # noqa: B017 - dataclass FrozenInstanceError
            _STUB_PROFILE.cpu_brand = "mutated"  # type: ignore[misc]

    def test_stub_profile_is_a_module_level_singleton(self):
        """Re-importing returns the same object (immutable, safe to share)."""
        from core.accel import _STUB_PROFILE as again

        assert again is _STUB_PROFILE
