"""ライブ認識用の自動ゲイン(AGC)。

音声が小さいと webrtcvad / Silero VAD / no_speech 判定がすべて「無音」側に
倒れて字幕が出ない。認識経路(VAD・whisper 直前)に限り、チャンク単位で
RMS を目標レベルへ正規化する。保存 WAV は原音のまま(本関数は純関数で、
呼び出し側も録音ファイルには適用しない)。

dBFS 規約は levels.rms_db と同一(フルスケール 32768 = 0dB、無音 = -80dB)。
"""
import numpy as np

from core.recording.levels import rms_db


def normalize_chunk(
    samples_int16: np.ndarray,
    target_db: float = -20.0,
    max_gain_db: float = 20.0,
    floor_db: float = -55.0,
) -> np.ndarray:
    """チャンクの RMS を target_db へ正規化した新しい int16 配列を返す。

    - rms < floor_db: ほぼ無音(ノイズ・空調)とみなし増幅しない。
    - rms >= target_db: 既に十分大きいので不変。
    - それ以外: gain_db = min(target_db - rms, max_gain_db) を乗算し、
      int16 範囲にクリップ(オーバーフロー防止)。
    入力配列は破壊しない。
    """
    if len(samples_int16) == 0:
        return samples_int16.copy()
    rms = rms_db(samples_int16)
    if rms < floor_db or rms >= target_db:
        return samples_int16.copy()
    gain_db = min(target_db - rms, max_gain_db)
    gain = 10.0 ** (gain_db / 20.0)
    boosted = samples_int16.astype(np.float32) * gain
    return np.clip(boosted, -32768.0, 32767.0).astype(np.int16)


def apply_gain(samples_int16: np.ndarray, gain_db: float) -> np.ndarray:
    """固定ゲイン(dB)を適用した新しい int16 配列を返す(手動ブースト用)。

    gain_db <= 0 と空配列は素通しコピー。増幅は int16 範囲にクリップ
    (オーバーフロー防止)。入力配列は破壊しない。
    """
    if len(samples_int16) == 0 or gain_db <= 0.0:
        return samples_int16.copy()
    gain = 10.0 ** (gain_db / 20.0)
    boosted = samples_int16.astype(np.float32) * gain
    return np.clip(boosted, -32768.0, 32767.0).astype(np.int16)
