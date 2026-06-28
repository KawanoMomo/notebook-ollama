"""録音中のチャンネル別ミュート状態(現在の真偽値のみ)を保持する純粋データ構造。

Teams 風のチャンネルミュート。チャンネル(``mic`` / ``system``)ごとに、現在
ミュート中かどうかの真偽値だけを持つ。ミュートの実体は「録音側で無音書き込み」
方式(recorder が ``is_muted`` を見て、ミュート中チャンネルの WAV に無音を書く)で
実現するため、ここでは区間タイムスタンプや永続化は扱わない。

なぜ区間方式をやめたか: WASAPI ループバックはアイドル時にフレームを落とすため
system.wav の時間軸が圧縮され、壁時計のミュート区間を WAV 位置へ定数オフセットで
写像できない(写像が非線形)。録音側で無音化すれば、STT・整文・話者分離・チャンク化・
埋め込み・推論のいずれにもミュート区間が到達しない(無音 → VAD で除去)。

スレッド安全性: WS ハンドラ(イベントループ)からの更新と、recorder スレッド /
live caption ゲートからの読み取りが並行しうる。``_lock`` で保護する(free-threaded
ビルドでも安全)。ロックは非競合なのでチャンク毎の取得でもコストは無視できる。
"""

from __future__ import annotations

# サポートするチャンネル名。recording_ws / live_caption の id_prefix とは独立に、
# データモデル上の正規キーをここで定義する。
CHANNELS: tuple[str, ...] = ("mic", "system")


class MuteState:
    """チャンネル別の現在ミュート状態(真偽値)ホルダ。"""

    def __init__(self) -> None:
        import threading

        self._lock = threading.Lock()
        self._muted: dict[str, bool] = {ch: False for ch in CHANNELS}

    def is_muted(self, channel: str) -> bool:
        """``channel`` が現在ミュート中か。未知チャンネルは常に False。"""
        with self._lock:
            return bool(self._muted.get(channel, False))

    def set_muted(self, channel: str, muted: bool) -> bool:
        """``channel`` のミュート状態を ``muted`` に設定する。

        未知チャンネルは無視する。状態が実際に変化したら True を返す
        (同状態への再設定は冪等で False)。
        """
        if channel not in self._muted:
            return False
        with self._lock:
            if self._muted[channel] == muted:
                return False
            self._muted[channel] = muted
            return True


def handle_mute_command(mute_state: MuteState, msg: object) -> dict | None:
    """クライアント→サーバの ``{"type":"mute","channel":...,"muted":...}`` を処理する。

    WS ハンドラから呼ばれる薄いロジック。実オーディオに依存しないので単体テスト可能。

    - ``msg`` が dict でない / ``type != "mute"`` / 未知チャンネル / フィールド欠落は
      None を返して無視する(後方互換: 古いクライアントが mute を送らなくても無害)。
    - ``muted`` は厳格に bool のみ(``"true"`` 等の文字列や 1 は無視)。
    - 状態を更新し、UI 同期用のエコー
      ``{"type":"mute_state","channel":...,"muted":...}`` を返す。冪等な場合も現在状態を
      反映したエコーを返して UI を同期させる。
    """
    if not isinstance(msg, dict):
        return None
    if msg.get("type") != "mute":
        return None
    channel = msg.get("channel")
    if channel not in CHANNELS:
        return None
    muted = msg.get("muted")
    if not isinstance(muted, bool):
        return None
    mute_state.set_muted(channel, muted)
    return {
        "type": "mute_state",
        "channel": channel,
        "muted": mute_state.is_muted(channel),
    }
