"""Unit tests for Recorder.stop() の terminate ガード (native SIGSEGV 回避)。

実音声ハードウェア無しで、teardown ロジックだけを検証する。

背景: WASAPI loopback が無音 (フレーム 0) の場合、旧実装では capture スレッドが
stream.read() 内で永久ブロックし stop() の join がタイムアウトしていた。その状態で
共有 PyAudio.terminate() を呼ぶと read 実行中の native 層と競合し segfault でサーバ
プロセスごと落ちる。stop() は「いずれかのスレッドがまだ alive なら terminate を
呼ばない」ガードを持つ。本テストはそのガードを fake で直接確認する。
"""
import importlib
from pathlib import Path

import pytest


def _load_recorder_cls():
    try:
        m = importlib.import_module("core.recording.recorder")
    except ImportError as e:  # pragma: no cover - recording extras 未導入環境
        pytest.skip(f"recording extras not installed: {e}")
    return m.Recorder


class _FakePyAudio:
    """terminate() の呼び出し回数を数える最小スタブ。"""

    def __init__(self):
        self.terminate_calls = 0

    def terminate(self):
        self.terminate_calls += 1


class _FakeChannel:
    """_ChannelRecorder の stop()/alive/error だけを模した最小スタブ。"""

    def __init__(self, alive: bool):
        self._alive = alive
        self.stop_calls = 0

    def stop(self):
        self.stop_calls += 1

    @property
    def alive(self) -> bool:
        return self._alive

    @property
    def error(self):
        return None


def _make_recorder(tmp_path: Path):
    Recorder = _load_recorder_cls()
    rec = Recorder(session_dir=tmp_path)
    # _open_lock は通常 start() で設定される。stop() が getattr で参照するため明示設定。
    import threading
    rec._open_lock = threading.Lock()
    return rec


def test_terminate_skipped_when_a_thread_is_still_alive(tmp_path):
    """Case A: いずれかのチャネルが alive==True → terminate を呼ばない。"""
    rec = _make_recorder(tmp_path)
    fake_pa = _FakePyAudio()
    rec._pa = fake_pa
    rec._mic = _FakeChannel(alive=True)   # join がタイムアウトし、まだ生きている想定
    rec._sys = _FakeChannel(alive=False)

    result = rec.stop()

    # SIGSEGV を避けるため terminate は呼ばれてはならない (= PyAudio をリークさせる)。
    assert fake_pa.terminate_calls == 0
    # _pa は None にクリアされる (二重 stop 防止)。
    assert rec._pa is None
    # stop() 自体はクラッシュせず結果 dict を返す。
    assert result == {"mic": None, "system": None}
    # 各チャネルの stop() は呼ばれている。
    assert rec._mic.stop_calls == 1
    assert rec._sys.stop_calls == 1


def test_terminate_called_when_all_threads_exited(tmp_path):
    """Case B: 全チャネルが alive==False → terminate を 1 回呼ぶ。"""
    rec = _make_recorder(tmp_path)
    fake_pa = _FakePyAudio()
    rec._pa = fake_pa
    rec._mic = _FakeChannel(alive=False)
    rec._sys = _FakeChannel(alive=False)

    result = rec.stop()

    assert fake_pa.terminate_calls == 1
    assert rec._pa is None
    assert result == {"mic": None, "system": None}


def test_terminate_called_when_channels_absent(tmp_path):
    """境界: _mic/_sys が None でも (alive 判定 False 扱い) terminate を呼ぶ。"""
    rec = _make_recorder(tmp_path)
    fake_pa = _FakePyAudio()
    rec._pa = fake_pa
    rec._mic = None
    rec._sys = None

    rec.stop()

    assert fake_pa.terminate_calls == 1
    assert rec._pa is None
