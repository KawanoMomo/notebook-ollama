"""Env-var helper for short-circuiting hardware probes in tests.

`HardwareProbe.run()` (wired in Task 1.6) checks `should_skip_probe()` first;
when True it returns the fixed `_STUB_PROFILE` from `core.accel` without
shelling out to `pnputil` / loading `ctranslate2` / poking `openvino`.

The env var must be the exact string "1" — any other value (None, empty,
"0", "true", "yes", "True") is treated as not-set so tests do not pick
the short-circuit by accident.
"""

from __future__ import annotations

import os

ENV_VAR_NAME = "NOTEBOOK_OLLAMA_SKIP_ACCEL_PROBE"


def should_skip_probe() -> bool:
    """Return True iff the skip-probe env var is set to the exact string "1"."""
    return os.environ.get(ENV_VAR_NAME) == "1"


__all__ = ["ENV_VAR_NAME", "should_skip_probe"]
