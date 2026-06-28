from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from core.ids import new_id


class RecordingBusyError(Exception):
    pass


@dataclass
class RecordingSession:
    id: str
    notebook_id: str
    session_dir: Path
    recorder: object
    live_caption: bool = False
    extras: dict = field(default_factory=dict)


class RecordingRegistry:
    def __init__(self) -> None:
        self._sessions: dict[str, RecordingSession] = {}

    @property
    def active_id(self) -> str | None:
        return next(iter(self._sessions), None)

    def start(
        self,
        notebook_id: str,
        session_dir: Path,
        recorder_factory: Callable[[], object],
        *,
        live_caption: bool = False,
    ) -> RecordingSession:
        if self._sessions:
            raise RecordingBusyError(
                "既に録音中です。停止してから開始してください。"
            )
        sid = new_id()
        sess = RecordingSession(
            id=sid,
            notebook_id=notebook_id,
            session_dir=session_dir,
            recorder=recorder_factory(),
            live_caption=live_caption,
        )
        self._sessions[sid] = sess
        return sess

    def get(self, sid: str) -> RecordingSession | None:
        return self._sessions.get(sid)

    def pop(self, sid: str) -> RecordingSession | None:
        return self._sessions.pop(sid, None)
