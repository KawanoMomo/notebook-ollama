"""MuteState(チャンネル別の現在ミュート真偽値ホルダ)の単体テスト。

ミュートの実体は recorder 側の無音書き込み。MuteState は真偽値を保持するだけで、
区間タイムスタンプや永続化は持たない(純粋ロジック、I/O なし)。
"""

from core.recording.mute_state import MuteState, handle_mute_command


def test_initial_state_is_unmuted():
    ms = MuteState()
    assert ms.is_muted("mic") is False
    assert ms.is_muted("system") is False


def test_set_muted_toggles_and_returns_change():
    ms = MuteState()
    assert ms.set_muted("mic", True) is True  # 変化した
    assert ms.is_muted("mic") is True
    assert ms.set_muted("mic", False) is True
    assert ms.is_muted("mic") is False


def test_set_muted_idempotent_returns_false():
    ms = MuteState()
    assert ms.set_muted("mic", True) is True
    assert ms.set_muted("mic", True) is False  # 同状態への再設定
    assert ms.set_muted("mic", False) is True
    assert ms.set_muted("mic", False) is False


def test_channels_are_independent():
    ms = MuteState()
    ms.set_muted("mic", True)
    assert ms.is_muted("mic") is True
    assert ms.is_muted("system") is False
    ms.set_muted("system", True)
    ms.set_muted("mic", False)
    assert ms.is_muted("mic") is False
    assert ms.is_muted("system") is True


def test_unknown_channel_ignored():
    ms = MuteState()
    assert ms.set_muted("speaker", True) is False
    assert ms.is_muted("speaker") is False


# --- handle_mute_command (WS の薄いロジック / 実オーディオ非依存) --------------


def test_handle_mute_command_sets_and_echoes():
    ms = MuteState()
    echo = handle_mute_command(ms, {"type": "mute", "channel": "mic", "muted": True})
    assert echo == {"type": "mute_state", "channel": "mic", "muted": True}
    assert ms.is_muted("mic") is True


def test_handle_mute_command_unmute_echoes():
    ms = MuteState()
    handle_mute_command(ms, {"type": "mute", "channel": "mic", "muted": True})
    echo = handle_mute_command(ms, {"type": "mute", "channel": "mic", "muted": False})
    assert echo == {"type": "mute_state", "channel": "mic", "muted": False}
    assert ms.is_muted("mic") is False


def test_handle_mute_command_ignores_unknown_type():
    ms = MuteState()
    assert handle_mute_command(ms, {"type": "level", "channel": "mic"}) is None
    assert ms.is_muted("mic") is False


def test_handle_mute_command_ignores_unknown_channel():
    ms = MuteState()
    assert (
        handle_mute_command(ms, {"type": "mute", "channel": "speaker", "muted": True})
        is None
    )


def test_handle_mute_command_ignores_missing_fields():
    ms = MuteState()
    assert handle_mute_command(ms, {"type": "mute", "channel": "mic"}) is None
    assert handle_mute_command(ms, {"type": "mute", "muted": True}) is None
    assert handle_mute_command(ms, {"type": "mute"}) is None
    assert ms.is_muted("mic") is False


def test_handle_mute_command_ignores_non_bool_muted():
    ms = MuteState()
    # "true" 文字列や 1 は無視(厳格に bool のみ)
    assert (
        handle_mute_command(ms, {"type": "mute", "channel": "mic", "muted": "true"})
        is None
    )
    assert (
        handle_mute_command(ms, {"type": "mute", "channel": "mic", "muted": 1}) is None
    )
    assert ms.is_muted("mic") is False


def test_handle_mute_command_ignores_non_dict():
    ms = MuteState()
    assert handle_mute_command(ms, "mute") is None
    assert handle_mute_command(ms, None) is None
    assert handle_mute_command(ms, ["mute"]) is None
