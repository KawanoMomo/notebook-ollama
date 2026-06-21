"""MuteState(チャンネル別ミュート区間アキュムレータ)の単体テスト。

純粋ロジック(I/O なし)+ JSON 永続化ヘルパのみを対象とする。
WASAPI / whisper には一切触れない。
"""

import json

from core.recording.mute_state import (
    MuteState,
    handle_mute_command,
    write_mute_intervals,
)


def test_initial_state_is_unmuted_and_empty():
    ms = MuteState()
    assert ms.is_muted("mic") is False
    assert ms.is_muted("system") is False
    assert ms.to_dict() == {"mic": [], "system": []}


def test_toggle_produces_closed_interval():
    ms = MuteState()
    assert ms.set_muted("mic", True, 70000) is True
    assert ms.is_muted("mic") is True
    # まだ閉じていないので to_dict には現れない
    assert ms.to_dict()["mic"] == []
    assert ms.set_muted("mic", False, 95000) is True
    assert ms.is_muted("mic") is False
    assert ms.to_dict()["mic"] == [{"start_ms": 70000, "end_ms": 95000}]
    # 触っていない system は空のまま
    assert ms.to_dict()["system"] == []


def test_channels_are_independent():
    ms = MuteState()
    ms.set_muted("mic", True, 1000)
    ms.set_muted("system", True, 1500)
    ms.set_muted("mic", False, 2000)
    # system はまだミュート中
    assert ms.is_muted("system") is True
    assert ms.is_muted("mic") is False
    assert ms.to_dict() == {
        "mic": [{"start_ms": 1000, "end_ms": 2000}],
        "system": [],
    }


def test_double_mute_is_idempotent():
    ms = MuteState()
    assert ms.set_muted("mic", True, 1000) is True
    # 既にミュート中に True を再送 -> 何もしない(区間の開始時刻は据え置き)
    assert ms.set_muted("mic", True, 1500) is False
    assert ms.set_muted("mic", False, 3000) is True
    # 区間は最初の True の時刻から始まる
    assert ms.to_dict()["mic"] == [{"start_ms": 1000, "end_ms": 3000}]


def test_double_unmute_is_idempotent():
    ms = MuteState()
    # ミュートしていない状態で False を送っても何も起きない
    assert ms.set_muted("mic", False, 500) is False
    assert ms.to_dict()["mic"] == []
    ms.set_muted("mic", True, 1000)
    ms.set_muted("mic", False, 2000)
    # 既にアンミュート済みに False 再送 -> 何もしない
    assert ms.set_muted("mic", False, 2500) is False
    assert ms.to_dict()["mic"] == [{"start_ms": 1000, "end_ms": 2000}]


def test_overlapping_toggles_produce_multiple_intervals():
    ms = MuteState()
    ms.set_muted("mic", True, 1000)
    ms.set_muted("mic", False, 2000)
    ms.set_muted("mic", True, 5000)
    ms.set_muted("mic", False, 6000)
    ms.set_muted("mic", True, 9000)
    ms.set_muted("mic", False, 10000)
    assert ms.to_dict()["mic"] == [
        {"start_ms": 1000, "end_ms": 2000},
        {"start_ms": 5000, "end_ms": 6000},
        {"start_ms": 9000, "end_ms": 10000},
    ]


def test_close_all_closes_open_intervals():
    ms = MuteState()
    ms.set_muted("mic", True, 1000)  # 開いたまま
    ms.set_muted("system", True, 1200)
    ms.set_muted("system", False, 1800)  # system は確定済み
    ms.close_all(now_ms=5000)
    assert ms.is_muted("mic") is False
    assert ms.is_muted("system") is False
    assert ms.to_dict() == {
        "mic": [{"start_ms": 1000, "end_ms": 5000}],
        "system": [{"start_ms": 1200, "end_ms": 1800}],
    }


def test_close_all_is_noop_when_nothing_open():
    ms = MuteState()
    ms.set_muted("mic", True, 1000)
    ms.set_muted("mic", False, 2000)
    ms.close_all(now_ms=5000)
    assert ms.to_dict()["mic"] == [{"start_ms": 1000, "end_ms": 2000}]


def test_unknown_channel_ignored():
    ms = MuteState()
    assert ms.set_muted("speaker", True, 1000) is False
    assert ms.is_muted("speaker") is False
    assert ms.to_dict() == {"mic": [], "system": []}


def test_end_never_before_start_on_clock_skew():
    ms = MuteState()
    ms.set_muted("mic", True, 5000)
    # 時計巻き戻り: now_ms が start より前でも end<start を作らない
    ms.set_muted("mic", False, 4000)
    iv = ms.to_dict()["mic"][0]
    assert iv["end_ms"] >= iv["start_ms"]


def test_write_mute_intervals_writes_json(tmp_path):
    ms = MuteState()
    ms.set_muted("mic", True, 70000)
    ms.set_muted("mic", False, 95000)
    rec_dir = tmp_path / "rec123"
    out = write_mute_intervals(ms, rec_dir)
    assert out == rec_dir / "mute_intervals.json"
    assert out.exists()
    loaded = json.loads(out.read_text(encoding="utf-8"))
    assert loaded == {
        "mic": [{"start_ms": 70000, "end_ms": 95000}],
        "system": [],
    }


def test_write_mute_intervals_creates_dir(tmp_path):
    ms = MuteState()
    rec_dir = tmp_path / "does" / "not" / "exist"
    out = write_mute_intervals(ms, rec_dir)
    assert out.exists()
    assert json.loads(out.read_text(encoding="utf-8")) == {"mic": [], "system": []}


# --- handle_mute_command (WS の薄いロジック / 実オーディオ非依存) --------------


def test_handle_mute_command_opens_interval_and_echoes():
    ms = MuteState()
    echo = handle_mute_command(ms, {"type": "mute", "channel": "mic", "muted": True}, 1000)
    assert echo == {"type": "mute_state", "channel": "mic", "muted": True}
    assert ms.is_muted("mic") is True


def test_handle_mute_command_closes_interval():
    ms = MuteState()
    handle_mute_command(ms, {"type": "mute", "channel": "mic", "muted": True}, 1000)
    echo = handle_mute_command(ms, {"type": "mute", "channel": "mic", "muted": False}, 4000)
    assert echo == {"type": "mute_state", "channel": "mic", "muted": False}
    assert ms.to_dict()["mic"] == [{"start_ms": 1000, "end_ms": 4000}]


def test_handle_mute_command_ignores_unknown_type():
    ms = MuteState()
    assert handle_mute_command(ms, {"type": "level", "channel": "mic"}, 1000) is None
    assert ms.is_muted("mic") is False


def test_handle_mute_command_ignores_unknown_channel():
    ms = MuteState()
    assert handle_mute_command(
        ms, {"type": "mute", "channel": "speaker", "muted": True}, 1000
    ) is None
    assert ms.to_dict() == {"mic": [], "system": []}


def test_handle_mute_command_ignores_missing_fields():
    ms = MuteState()
    assert handle_mute_command(ms, {"type": "mute", "channel": "mic"}, 1000) is None
    assert handle_mute_command(ms, {"type": "mute", "muted": True}, 1000) is None
    assert handle_mute_command(ms, {"type": "mute"}, 1000) is None
    assert ms.is_muted("mic") is False


def test_handle_mute_command_ignores_non_bool_muted():
    ms = MuteState()
    # "true" 文字列や 1 は無視(厳格に bool のみ)
    assert handle_mute_command(
        ms, {"type": "mute", "channel": "mic", "muted": "true"}, 1000
    ) is None
    assert handle_mute_command(
        ms, {"type": "mute", "channel": "mic", "muted": 1}, 1000
    ) is None
    assert ms.is_muted("mic") is False


def test_handle_mute_command_ignores_non_dict():
    ms = MuteState()
    assert handle_mute_command(ms, "mute", 1000) is None
    assert handle_mute_command(ms, None, 1000) is None
    assert handle_mute_command(ms, ["mute"], 1000) is None
