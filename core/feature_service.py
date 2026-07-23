from __future__ import annotations

from pathlib import Path

from core import settings_store
from core.exceptions import AppError, ErrorCode
from core.features import REGISTRY, get_flag, is_enabled

_SECTION = "beta_optins"


class FeatureService:
    """settings.json の beta_optins セクションを都度読み直すステートレスなサービス。

    このステートレス性のおかげで、build_context() (pipeline/generation 用) と
    main.py の lifespan (API 用) が独立に2つのインスタンスを持っても常に同じ
    設定を読む。将来 in-memory キャッシュを足す場合は、この2インスタンス分離が
    設定変更の反映漏れ(片方だけ古い値を見る)を起こさないか要検討。
    """

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
