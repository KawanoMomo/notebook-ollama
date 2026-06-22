"""_ChannelRecorder の「ミュート中は WAV に無音を書く」挙動の単体テスト。

実ハードウェア無しで、fake な pyaudio stream を流し込んで _run を直接駆動し、
mute_check=True のとき出力 WAV が無音(全ゼロ)になることを確認する。
"""
import importlib
import threading
import wave
from pathlib import Path

import numpy as np
import pytest


def _load_recorder_module():
    try:
        return importlib.import_module("core.recording.recorder")
    except ImportError as e:  # pragma: no cover - recording extras 未導入環境
        pytest.skip(f"recording extras not installed: {e}")


class _FakeStream:
    """get_read_available()/read() を備えた最小スタブ。frames を出し切ったら stop。"""

    def __init__(self, frames: list[bytes], stop_event: threading.Event):
        self._frames = frames
        self._stop = stop_event
        self._i = 0

    def get_read_available(self) -> int:
        return 2048 if self._i < len(self._frames) else 0

    def read(self, n, exception_on_overflow=False) -> bytes:
        data = self._frames[self._i]
        self._i += 1
        if self._i >= len(self._frames):
            self._stop.set()  # 最後のフレームを読んだら次のループで抜ける
        return data

    def stop_stream(self):
        pass

    def close(self):
        pass


class _FakePA:
    def __init__(self, stream):
        self._stream = stream

    def open(self, **kwargs):
        return self._stream


def _run_channel(tmp_path: Path, *, muted: bool) -> np.ndarray:
    m = _load_recorder_module()
    out = tmp_path / "ch.wav"
    # 16000Hz mono、リサンプル不要にして純粋に書き込み内容を見る。
    info = {"index": 0, "name": "fake", "sample_rate": 16000, "channels": 1}
    loud = (np.ones(1024, dtype=np.int16) * 1000).tobytes()
    rec = m._ChannelRecorder(
        info, out, target_sample_rate=16000,
        mute_check=(lambda: muted),
    )
    stream = _FakeStream([loud, loud, loud], rec._stop)
    rec._pa = _FakePA(stream)
    rec._run()  # 同期実行(fake stream が stop を立てる)
    with wave.open(str(out), "rb") as wf:
        frames = wf.readframes(wf.getnframes())
    return np.frombuffer(frames, dtype=np.int16)


def test_recorder_writes_silence_when_muted(tmp_path):
    arr = _run_channel(tmp_path, muted=True)
    assert arr.size > 0, "no frames written"
    assert np.all(arr == 0), "muted channel must be written as silence"


def test_recorder_passes_through_when_not_muted(tmp_path):
    arr = _run_channel(tmp_path, muted=False)
    assert arr.size > 0
    assert np.any(arr != 0), "unmuted channel must keep the captured audio"
