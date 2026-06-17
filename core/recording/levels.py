"""音声レベル計算ユーティリティ。録音中のレベルメータ表示に使う。"""

import numpy as np


def rms_db(samples_int16: np.ndarray) -> float:
    """int16 PCM サンプル列から RMS を dB に変換する。

    フルスケール (32768) を 0 dB、無音を -80 dB とする。
    """
    if len(samples_int16) == 0:
        return -80.0
    audio = samples_int16.astype(np.float32)
    mean_square = float(np.mean(audio * audio))
    if mean_square < 1.0:
        return -80.0
    rms = np.sqrt(mean_square)
    db = 20.0 * np.log10(rms / 32768.0)
    return max(-80.0, db)


def peak_db(samples_int16: np.ndarray) -> float:
    """ピークレベル (絶対値最大) を dB に。"""
    if len(samples_int16) == 0:
        return -80.0
    peak = float(np.max(np.abs(samples_int16)))
    if peak < 1.0:
        return -80.0
    return max(-80.0, 20.0 * np.log10(peak / 32768.0))


class LevelMeter:
    """N サンプルごとにレベルを on_level コールバックに出力する thottle。

    on_chunk と組み合わせて、音声が来るたびに評価し閾値を超えたら通知。
    最小通知間隔 (min_interval_ms) で間引いて WebSocket 負荷を抑える。
    """

    def __init__(
        self,
        channel: str,
        on_level,  # Callable[[dict], None]
        min_interval_ms: int = 100,
        sample_rate: int = 16000,
    ):
        import time
        self._channel = channel
        self._on_level = on_level
        self._min_interval_s = min_interval_ms / 1000.0
        self._last_push = 0.0
        self._sample_rate = sample_rate

    def __call__(self, samples_int16) -> None:
        import time
        now = time.monotonic()
        if (now - self._last_push) < self._min_interval_s:
            return
        self._last_push = now
        rms = rms_db(samples_int16)
        peak = peak_db(samples_int16)
        try:
            self._on_level({
                "type": "level",
                "channel": self._channel,
                "rms_db": round(rms, 1),
                "peak_db": round(peak, 1),
            })
        except Exception:
            pass
