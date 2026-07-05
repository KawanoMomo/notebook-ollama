"""DevSinkHandler — structlog / stdlib logging の両面からリングへ吸い込む口(仕様 §8.1)。

- 先頭の enabled チェック 1 回で無効時は即 return(NFR-1)
- 例外は握り潰して本流を守る(NFR-2)。失敗の記録は "dev_logs" ロガーに 1 行だけ
- "dev_logs" ロガー自身のレコードは吸わない(無限ループ防止)
"""
from __future__ import annotations

import datetime as _dt
import logging
from typing import Any

from core.dev_logs.broker import DevBroker
from core.dev_logs.ring import DevLogRing

_fallback_log = logging.getLogger("dev_logs")

_LEVEL_MAP = {
    "debug": "debug",
    "info": "info",
    "warning": "warn",
    "warn": "warn",
    "error": "error",
    "critical": "error",
    "exception": "error",
}


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def push_dev_entry(
    *,
    ring: DevLogRing,
    broker: DevBroker | None,
    level: str,
    source: str,
    msg: str,
    payload: dict[str, Any],
    ts: str | None = None,
) -> None:
    """entry 化 → ring.push → broker.publish の共通経路。例外は握り潰す。"""
    if not ring.enabled:
        return
    try:
        entry = {
            "ts": ts or _now_iso(),
            "level": _LEVEL_MAP.get(level.lower(), "info"),
            "source": source,
            "msg": msg,
            "payload": payload,
        }
        seq = ring.push(entry)
        if seq and broker is not None:
            broker.publish_threadsafe({"event": "entry", "data": {**entry, "seq": seq}})
    except Exception:  # noqa: S110 — Dev 側の失敗で本流を止めない(NFR-2)
        try:
            _fallback_log.warning("dev sink push failed")
        except Exception:  # noqa: S110
            pass


class DevSinkHandler(logging.Handler):
    """stdlib logging 側の吸い口(uvicorn アクセスログ・例外など)。"""

    def __init__(self, *, ring: DevLogRing, broker: DevBroker | None) -> None:
        super().__init__(level=logging.INFO)
        self._ring = ring
        self._broker = broker

    def emit(self, record: logging.LogRecord) -> None:
        if not self._ring.enabled:
            return
        if record.name == "dev_logs" or record.name.startswith("dev_logs."):
            return
        try:
            payload: dict[str, Any] = {"logger": record.name}
            if record.exc_info and record.exc_info[0] is not None:
                payload["exc_type"] = record.exc_info[0].__name__
            push_dev_entry(
                ring=self._ring,
                broker=self._broker,
                level=record.levelname,
                source="app",
                msg=record.getMessage(),
                payload=payload,
            )
        except Exception:  # noqa: S110
            pass


def make_dev_structlog_processor(*, ring: DevLogRing, broker: DevBroker | None):
    """structlog パイプラインに挿す processor。event_dict は素通しで返す。"""

    def processor(_logger: Any, method_name: str, event_dict: dict) -> dict:
        if not ring.enabled:
            return event_dict
        try:
            d = dict(event_dict)
            msg = str(d.pop("event", "") or "")
            level = str(d.pop("level", method_name) or method_name)
            d.pop("timestamp", None)
            push_dev_entry(
                ring=ring,
                broker=broker,
                level=level,
                source="app",
                msg=msg,
                payload=d,
            )
        except Exception:  # noqa: S110
            pass
        return event_dict

    return processor
