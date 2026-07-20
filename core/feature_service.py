from __future__ import annotations

from pathlib import Path

from core import settings_store
from core.exceptions import AppError, ErrorCode
from core.features import REGISTRY, get_flag, is_enabled

_SECTION = "beta_optins"


class FeatureService:
    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir

    def _optins(self) -> dict[str, bool]:
        ov = settings_store.load_overrides(self._data_dir).get(_SECTION)
        return ov if isinstance(ov, dict) else {}

    def is_enabled(self, flag_id: str) -> bool:
        return is_enabled(flag_id, self._optins())

    def set_optin(self, flag_id: str, enabled: bool) -> None:
        flag = get_flag(flag_id)
        if flag is None:
            raise AppError(ErrorCode.STORAGE_NOT_FOUND, f"unknown feature flag: {flag_id}")
        if flag.stage == "ga":
            raise AppError(
                ErrorCode.VALIDATION_FAILED, "GA機能のオプトインは変更できません"
            )
        optins = {k: v for k, v in self._optins().items() if get_flag(k) is not None}
        optins[flag_id] = bool(enabled)
        settings_store.save_section(self._data_dir, _SECTION, optins)

    def list_flags(self) -> list[dict]:
        optins = self._optins()
        return [
            {
                "id": f.id,
                "name": f.name,
                "description": f.description,
                "stage": f.stage,
                "enabled": is_enabled(f.id, optins),
            }
            for f in REGISTRY
        ]
