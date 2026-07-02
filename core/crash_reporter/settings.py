"""クラッシュレポート機能のユーザ設定モデル。

spec §7.3 / plan Sprint 3 Task 3.2。

- ``enabled``      : ``True`` = 送信オプトイン済 / ``False`` = 明示的オプトアウト /
                     ``None`` = 未決定 (初回オプトインダイアログをまだ出していない)。
                     ``False`` と ``None`` を区別することで「もう聞かない/まだ聞いてない」
                     を別状態として扱える (UI 側のオプトインフロー設計の前提)。
- ``auto_prompt``  : クラッシュ検知時に自動でオプトインダイアログを出すかどうか。
                     既定 ``True``。一度ユーザが「次から自動で出さない」を選んだら
                     ``False`` に落として永続化する想定。
- ``opted_in_at``  : オプトイン (または明示的オプトアウト) を記録した時刻。
                     ``datetime`` で持ち、settings.json には ISO 8601 文字列として
                     永続化される (pydantic の ``model_dump(mode='json')``)。

`core.config.AppConfig.crash_report` フィールドとして組み込まれ、
`core.settings_store` の ``apply_overrides`` / ``save_crash_report`` /
``load_crash_report`` 経由で ``settings.json`` の ``crash_report`` セクションに
``audio`` / ``ollama`` と同じ規約で保存される。
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class CrashReportSettings(BaseModel):
    """クラッシュレポート関連のユーザ設定 (spec §7.3)。"""

    enabled: bool | None = None
    """``None`` = 初回オプトイン未決定。``True`` / ``False`` で明示状態。"""

    auto_prompt: bool = True
    """クラッシュ検知時に自動でオプトインダイアログを出すか。"""

    opted_in_at: datetime | None = None
    """オプトイン / 明示的オプトアウトを記録した UTC 時刻。"""
