"""録音中のチャンネル別ミュート区間を蓄積する純粋データ構造。

Teams 風の時間区間ミュート(M1)。チャンネル(``mic`` / ``system``)ごとに、
ミュート ON で区間を開き、OFF で確定する。録音停止時に開いたままの区間は
``close_all`` で録音終了時刻にクローズする。

時間基準は「録音開始 = 0ms」。すべての ms は録音開始からの相対値。
WASAPI/whisper 等の I/O を一切持たない純粋ロジックなので、単体テスト可能で、
``to_dict`` の結果をそのまま ``mute_intervals.json`` に永続化できる。
"""

from __future__ import annotations

import json
from pathlib import Path

# サポートするチャンネル名。recording_ws / live_caption の id_prefix とは独立に、
# データモデル(mute_intervals.json)上の正規キーをここで定義する。
CHANNELS: tuple[str, ...] = ("mic", "system")


class MuteState:
    """チャンネル別ミュート区間アキュムレータ。

    内部状態(チャンネルごと):
      - ``_muted``: 現在ミュート中か(bool)
      - ``_open_start``: 現在開いている区間の開始 ms(ミュート中のみ非 None)
      - ``_closed``: 確定済み区間 ``[{"start_ms", "end_ms"}, ...]``

    スレッド安全性: WS ハンドラ(イベントループ)からの更新と、live caption の
    供給ゲート(録音スレッド)からの読み取りが並行しうる。区間の開閉(リスト変更)
    と ``is_muted`` の読み取りはいずれも ``_lock`` で保護する(free-threaded ビルド
    でも安全)。ロックは非競合なのでチャンク毎の取得でもコストは無視できる。
    """

    def __init__(self) -> None:
        import threading

        self._lock = threading.Lock()
        self._muted: dict[str, bool] = {ch: False for ch in CHANNELS}
        self._open_start: dict[str, int | None] = {ch: None for ch in CHANNELS}
        self._closed: dict[str, list[dict]] = {ch: [] for ch in CHANNELS}

    def is_muted(self, channel: str) -> bool:
        """``channel`` が現在ミュート中か。未知チャンネルは常に False。

        非競合な ``_lock`` を取って読む(オーディオチャンク毎の取得でも軽量)。
        bool 読み取りは CPython の GIL 下では原子的だが、free-threaded ビルドでは
        保証されないため、明示的にロックして安全側に倒す。
        """
        with self._lock:
            return bool(self._muted.get(channel, False))

    def set_muted(self, channel: str, muted: bool, now_ms: int) -> bool:
        """``channel`` のミュート状態を ``muted`` に設定する。

        - False→True: ``now_ms`` で区間を開く。
        - True→False: 開いている区間を ``end_ms=now_ms`` で確定する。
        - 同状態への再設定(double-mute / double-unmute)は冪等で何もしない。

        未知チャンネルは無視する。状態が実際に変化したら True を返す。
        """
        if channel not in self._muted:
            return False
        now_ms = int(now_ms)
        with self._lock:
            cur = self._muted[channel]
            if muted == cur:
                return False  # 冪等: 同状態への再設定は無視
            if muted:
                self._muted[channel] = True
                self._open_start[channel] = now_ms
            else:
                start = self._open_start[channel]
                self._muted[channel] = False
                self._open_start[channel] = None
                if start is not None:
                    # end が start より前(時計巻き戻り等)になっても end<start を作らない。
                    end = max(now_ms, start)
                    self._closed[channel].append({"start_ms": start, "end_ms": end})
            return True

    def close_all(self, now_ms: int) -> None:
        """録音終了時に、開いたままの全区間を ``end_ms=now_ms`` でクローズする。"""
        now_ms = int(now_ms)
        with self._lock:
            for ch in CHANNELS:
                if self._muted[ch] and self._open_start[ch] is not None:
                    start = self._open_start[ch]
                    end = max(now_ms, start)
                    self._closed[ch].append({"start_ms": start, "end_ms": end})
                    self._muted[ch] = False
                    self._open_start[ch] = None

    def to_dict(self) -> dict[str, list[dict]]:
        """確定済み区間を ``{"mic": [...], "system": [...]}`` で返す(deep copy)。

        開いたままの区間は含めない(永続化前に ``close_all`` を呼ぶこと)。
        """
        with self._lock:
            return {
                ch: [dict(iv) for iv in self._closed[ch]] for ch in CHANNELS
            }


def handle_mute_command(
    mute_state: MuteState, msg: object, now_ms: int
) -> dict | None:
    """クライアント→サーバの ``{"type":"mute","channel":...,"muted":...}`` を処理する。

    WS ハンドラから呼ばれる薄いロジック。実オーディオに依存しないので単体テスト可能。

    - ``msg`` が dict でない / ``type != "mute"`` / 未知チャンネル / フィールド欠落は
      None を返して無視する(後方互換: 古いクライアントが mute を送らなくても無害)。
    - ``muted`` は bool に正規化する(``"true"`` 等の文字列は無視: 厳格に bool のみ)。
    - 状態を更新し、UI 同期用のエコー
      ``{"type":"mute_state","channel":...,"muted":...}`` を返す。状態が実際に
      変化しなかった(冪等)場合も、現在状態を反映したエコーを返して UI を同期させる。
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
    mute_state.set_muted(channel, muted, now_ms)
    return {
        "type": "mute_state",
        "channel": channel,
        "muted": mute_state.is_muted(channel),
    }


# 永続化スキーマのバージョン。形状を変えたら上げる(2-BE2 がこれで読み分ける)。
MUTE_INTERVALS_VERSION = 1


def write_mute_intervals(
    mute_state: MuteState,
    recording_dir: Path,
    *,
    wav_start_offset_ms: int = 0,
) -> Path:
    """``mute_state`` を ``recording_dir/mute_intervals.json`` へ永続化する。

    録音ディレクトリ(mic.wav / system.wav と同階層)にサイドカー JSON を書く。
    書き込んだパスを返す。

    永続化形状(version 1):
    ::

        {
          "version": 1,
          "wav_start_offset_ms": <int>,
          "mic":    [{"start_ms":.., "end_ms":..}, ...],
          "system": [...]
        }

    - ``mic`` / ``system`` の区間 ms は従来どおり「録音開始(t0)= 0ms」相対。
    - ``wav_start_offset_ms`` = (wav_t0 - t0) の ms。オフラインフィルタ(2-BE2)は
      各区間 ms からこの値を **減算** して WAV 先頭相対 ms に変換する。WAV の時間
      基準が不明なら 0(その場合 2-BE2 は仕様の保守的境界規則「重なれば除外」に
      頼る)。
    """
    recording_dir = Path(recording_dir)
    recording_dir.mkdir(parents=True, exist_ok=True)
    out = recording_dir / "mute_intervals.json"
    channels = mute_state.to_dict()
    payload = {
        "version": MUTE_INTERVALS_VERSION,
        "wav_start_offset_ms": int(wav_start_offset_ms),
        **channels,
    }
    out.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return out
