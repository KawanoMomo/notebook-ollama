"""録音中チャンクを VAD + faster-whisper で逐次認識する。

メモリにオーディオを蓄積し、一定長 (chunk_sec) たまったら VAD で発話区間を検出、
発話があれば transcriber で起こして on_caption コールバックに渡す。
"""

import threading
import time
from typing import Callable, Optional

import numpy as np

from core.recording.agc import apply_gain, normalize_chunk


class LiveCaption:
    """録音と並行して動くチャンク STT ワーカ。

    使い方:
        lc = LiveCaption(transcriber, on_caption=lambda c: print(c))
        lc.start()
        # ... マイクチャンク到着のたびに lc.accept(arr) を呼ぶ ...
        lc.stop()
    """

    def __init__(
        self,
        transcriber,  # core.recording.transcriber.Transcriber インスタンス
        on_caption: Callable[[dict], None],
        chunk_sec: float = 5.0,
        overlap_sec: float = 1.0,
        sample_rate: int = 16000,
        vad_aggressiveness: int = 2,
        label: str = "",
        epoch: Optional[float] = None,
        id_prefix: str = "",
        caption_sink: Optional[Callable[[list], None]] = None,
        agc_enabled: bool = True,
        agc_target_db: float = -20.0,
        agc_max_gain_db: float = 20.0,
        agc_floor_db: float = -55.0,
    ):
        import webrtcvad
        self._transcriber = transcriber
        self._on_caption = on_caption
        self._label = label
        self._id_prefix = id_prefix
        # caption_sink([{id,start_ms,end_ms}, ...]): 発行した字幕のメタを LiveDiarizer に
        # 登録する (システム音のみ)。バックグラウンド話者分離がラベルを後追いで更新する。
        self._caption_sink = caption_sink
        self._cap_n = 0
        self._agc_enabled = agc_enabled
        self._agc_target_db = agc_target_db
        self._agc_max_gain_db = agc_max_gain_db
        self._agc_floor_db = agc_floor_db
        self._boost_db = 0.0   # 手動ブースト(dB)。録音中に API から変更される
        self._chunk_samples = int(chunk_sec * sample_rate)
        self._overlap_samples = int(overlap_sec * sample_rate)
        self._sample_rate = sample_rate
        self._vad = webrtcvad.Vad(vad_aggressiveness)
        self._buffer = np.zeros(0, dtype=np.int16)
        self._buf_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._origin_ms = 0  # fallback 用: 処理済の累積 ms (epoch 未指定時)
        # mic/system で字幕タイムスタンプを揃えるための共有時刻基準 (perf_counter)。
        # 両 LiveCaption が同じ epoch を共有することで、別スレッド・別ストリームの
        # 開始タイミング差やドロップに依らず同一タイムラインに揃う。
        self._epoch = epoch
        self._buf_end_ms: Optional[float] = None  # buffer 末尾サンプルの epoch 相対 wall-clock(ms)
        self._pending_base_ms = 0  # 直近 pop した chunk の先頭時刻(ms)

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=10)

    def accept(self, samples: np.ndarray) -> None:
        """Recorder スレッドから呼ばれる。int16 mono 16kHz samples を蓄積する。"""
        with self._buf_lock:
            if self._epoch is not None:
                # このブロックは概ね「今」到着した = buffer 末尾の wall-clock(epoch 相対)。
                self._buf_end_ms = (time.perf_counter() - self._epoch) * 1000.0
            self._buffer = np.concatenate([self._buffer, samples])

    def _pop_chunk(self) -> Optional[np.ndarray]:
        with self._buf_lock:
            if len(self._buffer) < self._chunk_samples:
                return None
            chunk = self._buffer[: self._chunk_samples].copy()
            # この chunk 先頭の絶対時刻を算出 (mic/system 共通の epoch 基準)。
            if self._epoch is not None and self._buf_end_ms is not None:
                buf_start_ms = self._buf_end_ms - (len(self._buffer) / self._sample_rate) * 1000.0
                self._pending_base_ms = int(max(0.0, buf_start_ms))
            else:
                self._pending_base_ms = int(self._origin_ms)  # fallback (epoch 未指定)
            # overlap_samples を残して前方を破棄
            keep_from = self._chunk_samples - self._overlap_samples
            self._buffer = self._buffer[keep_from:]
            self._origin_ms += int((keep_from / self._sample_rate) * 1000)
            return chunk

    def set_boost_db(self, db: float) -> None:
        """手動ブースト(dB)を設定する。次チャンクの認識前処理から反映される。
        float 代入はアトミックなのでロック不要(読み手はワーカスレッドのみ)。"""
        self._boost_db = float(db)

    def _prepare_chunk(self, chunk: np.ndarray) -> np.ndarray:
        """認識前処理。手動ブースト → 自動AGC の順に適用する(失敗時は原音)。"""
        try:
            if self._boost_db > 0.0:
                chunk = apply_gain(chunk, self._boost_db)
            if self._agc_enabled:
                chunk = normalize_chunk(chunk, self._agc_target_db,
                                        self._agc_max_gain_db, self._agc_floor_db)
            return chunk
        except Exception:
            return chunk    # 前処理失敗で字幕を止めない

    def _has_speech(self, audio_int16: np.ndarray) -> bool:
        """webrtcvad は 10/20/30ms フレーム単位、16-bit PCM only。"""
        frame_len = int(self._sample_rate * 0.02)  # 20ms
        speech_frames = 0
        total_frames = 0
        for i in range(0, len(audio_int16) - frame_len + 1, frame_len):
            frame = audio_int16[i : i + frame_len].tobytes()
            total_frames += 1
            try:
                if self._vad.is_speech(frame, self._sample_rate):
                    speech_frames += 1
            except Exception:
                continue
        if total_frames == 0:
            return False
        return (speech_frames / total_frames) >= 0.1  # 10% 以上発話

    def _run(self) -> None:
        import sys
        chunks_processed = 0
        while not self._stop_event.is_set():
            chunk = self._pop_chunk()
            if chunk is None:
                time.sleep(0.1)
                continue
            chunks_processed += 1
            base_ms = self._pending_base_ms  # mic/system 共通 epoch 基準の chunk 先頭時刻
            chunk = self._prepare_chunk(chunk)   # AGC: VAD と whisper の両方が増幅後を見る
            if not self._has_speech(chunk):
                # 無音情報も surface (ハートビート代わり)
                try:
                    self._on_caption({
                        "type": "info",
                        "msg": f"chunk #{chunks_processed} silent",
                        "start_ms": base_ms,
                        "label": self._label,
                    })
                except Exception:
                    pass
                continue
            try:
                segments = self._transcriber.transcribe_array(
                    chunk.astype(np.float32) / 32768.0,
                    sample_rate=self._sample_rate,
                    language="ja",
                    base_ms=base_ms,
                )
            except Exception as e:
                print(f"[live-caption] transcribe failed: {type(e).__name__}: {e}",
                      file=sys.stderr, flush=True)
                try:
                    self._on_caption({
                        "type": "error",
                        "msg": f"transcribe failed: {type(e).__name__}: {e}",
                        "label": self._label,
                    })
                except Exception:
                    pass
                continue
            chunk_meta: list = []
            for seg in segments:
                self._cap_n += 1
                cap_id = (f"{self._id_prefix}-{self._cap_n}"
                          if self._id_prefix else str(self._cap_n))
                chunk_meta.append({"id": cap_id,
                                   "start_ms": seg["start_ms"], "end_ms": seg["end_ms"]})
                try:
                    self._on_caption({
                        "type": "caption",
                        "id": cap_id,
                        "start_ms": seg["start_ms"],
                        "end_ms": seg["end_ms"],
                        "text": seg["text"],
                        "language": seg["language"],
                        "is_final": False,
                        "label": self._label,
                    })
                except Exception:
                    pass
            # システム音のみ: 発行した字幕メタを LiveDiarizer に登録する。
            # バックグラウンド話者分離が後追いで caption_update を送る。
            if self._caption_sink is not None and chunk_meta:
                try:
                    self._caption_sink(chunk_meta)
                except Exception as e:
                    print(f"[live-caption] caption_sink failed: {type(e).__name__}: {e}",
                          file=sys.stderr, flush=True)
