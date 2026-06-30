"""WASAPI loopback + マイク 同時 2ch 録音。"""

# threading.Lock は class ではなく factory function なので、ランタイムでの
# `threading.Lock | None` 評価が TypeError になる。PEP 563 で annotation を
# 文字列化することで回避する (UP045 auto-fix 由来の互換問題)。
from __future__ import annotations

import contextlib
import threading
import wave
from collections.abc import Callable
from pathlib import Path


def list_input_devices() -> list[dict]:
    """利用可能な入力デバイス (マイク + loopback) を返す。

    戻り値: [{index, name, max_channels, default_sample_rate, is_loopback}, ...]
    """
    import pyaudiowpatch as pyaudio
    out: list[dict] = []
    with pyaudio.PyAudio() as p:
        for i in range(p.get_device_count()):
            info = p.get_device_info_by_index(i)
            if info["maxInputChannels"] <= 0:
                continue
            out.append({
                "index": int(info["index"]),
                "name": str(info["name"]),
                "max_channels": int(info["maxInputChannels"]),
                "default_sample_rate": float(info["defaultSampleRate"]),
                "is_loopback": bool(info.get("isLoopbackDevice", False)),
            })
    return out


def find_default_loopback_index() -> int | None:
    """既定出力デバイスに対応する loopback デバイスの index を返す。"""
    import pyaudiowpatch as pyaudio
    with pyaudio.PyAudio() as p:
        try:
            wasapi = p.get_host_api_info_by_type(pyaudio.paWASAPI)
        except OSError:
            return None
        default_out_idx = wasapi.get("defaultOutputDevice")
        if default_out_idx is None or default_out_idx < 0:
            return None
        try:
            default_out = p.get_device_info_by_index(default_out_idx)
        except OSError:
            return None
        target = f"{default_out['name']} [Loopback]"
        for lb in p.get_loopback_device_info_generator():
            # 厳密マッチ + 入力 ch >0 を必須化 (誤検出防止)
            if lb["name"] == target and int(lb["maxInputChannels"]) > 0:
                return int(lb["index"])
    return None


def find_default_mic_index() -> int | None:
    """既定マイクデバイスの index。"""
    import pyaudiowpatch as pyaudio
    with pyaudio.PyAudio() as p:
        try:
            info = p.get_default_input_device_info()
            return int(info["index"])
        except OSError:
            return None


def resolve_device_info(device_index: int) -> dict | None:
    """デバイス情報を一度だけ確実に取得する。

    pyaudio の get_device_info_by_index は PyAudio インスタンスごとに
    呼ぶと index がずれる可能性があるので、API レイヤで一度確定させて
    Recorder には dict を渡す方式に統一する。
    """
    import pyaudiowpatch as pyaudio
    with pyaudio.PyAudio() as p:
        try:
            info = p.get_device_info_by_index(device_index)
        except OSError:
            return None
        ch = int(info.get("maxInputChannels", 0))
        if ch <= 0:
            return None
        return {
            "index": int(info["index"]),
            "name": str(info.get("name", "?")),
            "sample_rate": int(info.get("defaultSampleRate", 16000)),
            "channels": ch,
            "is_loopback": bool(info.get("isLoopbackDevice", False)),
        }


class _ChannelRecorder:
    """単一デバイスの録音ワーカ。pyaudio フレームを wav に逐次書き込む。

    device_info は事前解決した dict {index, name, sample_rate, channels} を渡す。
    """

    def __init__(
        self,
        device_info: dict,
        out_path: Path,
        target_sample_rate: int = 16000,
        on_chunk: Callable | None = None,
        pyaudio_instance=None,
        open_lock: threading.Lock | None = None,
        mute_check: Callable[[], bool] | None = None,
    ):
        self._device_info = device_info
        self._device_index = int(device_info["index"])
        self._src_sr = int(device_info["sample_rate"])
        self._src_ch = int(device_info["channels"])
        self._device_name = str(device_info.get("name", "?"))
        self._out_path = out_path
        self._target_sr = target_sample_rate
        self._on_chunk = on_chunk
        # ミュート中はこのチャンネルの WAV に実音声でなく無音を書く(設計: 録音側ミュート)。
        # これにより、ミュート区間は STT・整文・話者分離・チャンク化・埋め込み・推論の
        # いずれにも到達しない(無音 → VAD で除去)。ループバックがアイドル時にフレームを
        # 落とし WAV 時間軸が圧縮される問題があっても、タイムスタンプ計算に依存せず確実。
        self._mute_check = mute_check
        self._pa = pyaudio_instance  # 親 Recorder から共有される
        self._open_lock = open_lock or threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._error: Exception | None = None
        self._exited = False  # _run の実行ループが最後まで抜けたか (teardown 安全判定用)

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    @property
    def error(self) -> Exception | None:
        return self._error

    @property
    def alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _run(self) -> None:
        import sys
        import time
        chunk_count = 0
        src_sr = self._src_sr
        src_ch = self._src_ch
        try:
            import numpy as np
            import pyaudiowpatch as pyaudio
            p = self._pa
            assert p is not None, "pyaudio_instance must be provided by Recorder"
            print(
                f"[recorder] starting device idx={self._device_index} "
                f"name='{self._device_name}' sr={src_sr} ch={src_ch} -> {self._out_path}",
                file=sys.stderr, flush=True,
            )
            # PyAudio.open は thread-safe ではないので、Recorder 全体で排他する
            with self._open_lock:
                stream = p.open(
                    format=pyaudio.paInt16,
                    channels=src_ch,
                    rate=src_sr,
                    frames_per_buffer=1024,
                    input=True,
                    input_device_index=self._device_index,
                )
            self._out_path.parent.mkdir(parents=True, exist_ok=True)
            wf = wave.open(str(self._out_path), "wb")
            wf.setnchannels(1)  # 出力は常にモノラル
            wf.setsampwidth(2)
            wf.setframerate(self._target_sr)
            try:
                while not self._stop.is_set():
                    try:
                        avail = stream.get_read_available()
                    except Exception:
                        avail = 0
                    if avail < 1024:
                        # No (or not enough) audio yet — e.g. an idle loopback that
                        # yields no frames. Do NOT block in stream.read(); sleep
                        # briefly and re-check _stop so stop()/join() always succeeds.
                        time.sleep(0.01)
                        continue
                    try:
                        data = stream.read(1024, exception_on_overflow=False)
                    except Exception as e:
                        if chunk_count < 5:
                            print(f"[recorder] stream.read failed (idx={self._device_index}): {e}",
                                  file=sys.stderr, flush=True)
                        continue
                    # int16 PCM → numpy
                    arr = np.frombuffer(data, dtype=np.int16)
                    if src_ch > 1:
                        arr = arr.reshape(-1, src_ch).mean(axis=1).astype(np.int16)
                    # サンプリングレート変換 (簡易: scipy か numpy で linear interp)
                    if src_sr != self._target_sr:
                        ratio = self._target_sr / src_sr
                        new_len = int(len(arr) * ratio)
                        if new_len > 0:
                            x_old = np.linspace(0, 1, len(arr), endpoint=False)
                            x_new = np.linspace(0, 1, new_len, endpoint=False)
                            arr = np.interp(x_new, x_old, arr).astype(np.int16)
                    # ミュート中はこのチャンネルを無音化して WAV に書く(実音声は残さない)。
                    # WAV 長は実音声時と同じだけ進むが内容は無音なので、下流の STT 以降に
                    # ミュート区間の発話が一切到達しない。
                    if self._mute_check is not None and self._mute_check():
                        arr = np.zeros_like(arr)
                    wf.writeframes(arr.tobytes())
                    chunk_count += 1
                    if chunk_count == 1:
                        print(f"[recorder] first chunk read OK from idx={self._device_index} "
                              f"({len(arr)} samples @ {self._target_sr}Hz)",
                              file=sys.stderr, flush=True)
                    if self._on_chunk is not None:
                        try:
                            self._on_chunk(arr)
                        except Exception as e:
                            if chunk_count < 5:
                                print(f"[recorder] on_chunk callback failed: {e}",
                                      file=sys.stderr, flush=True)
            finally:
                print(f"[recorder] stopping idx={self._device_index} chunks={chunk_count}",
                      file=sys.stderr, flush=True)
                # Best-effort teardown: WAV header may already be flushed; even
                # if close() raises, we must continue to close the audio stream
                # below so the device is released for the next session.
                with contextlib.suppress(Exception):
                    wf.close()
                # ストリーム破棄を open と同じ lock で直列化し、共有 PyAudio 上での
                # 並行 close / terminate 競合 (native segfault) を避ける。
                with self._open_lock:
                    # Best-effort: even on failure to stop the stream, close()
                    # below still has to run so the underlying handle is freed.
                    with contextlib.suppress(Exception):
                        stream.stop_stream()
                    # Best-effort: PyAudio.terminate() (called later by Recorder)
                    # would mask any close() exception anyway; swallow here so
                    # the second channel's teardown is not skipped.
                    with contextlib.suppress(Exception):
                        stream.close()
        except Exception as e:
            self._error = e
            print(f"[recorder] FATAL idx={self._device_index}: {type(e).__name__}: {e}",
                  file=sys.stderr, flush=True)
        finally:
            # 正常終了でもエラー終了でも、ここに到達した時点で run ループは抜けている。
            # stop() 側の terminate ガードが alive と併せて参照する teardown フラグ。
            self._exited = True


class Recorder:
    """マイク + システム音 (WASAPI loopback) を別 wav に同時録音する。

    使い方:
        rec = Recorder(session_dir=Path("data/audio/<sid>"))
        rec.start(mic_index=None, system_index=None)  # None で既定デバイス
        # ... ユーザーが停止ボタンを押すまで待つ ...
        rec.stop()
        # → session_dir/mic.wav と session_dir/system.wav が生成される
    """

    def __init__(self, session_dir: Path, sample_rate: int = 16000):
        self._session_dir = session_dir
        self._sample_rate = sample_rate
        self._mic: _ChannelRecorder | None = None
        self._sys: _ChannelRecorder | None = None
        self._mic_path = session_dir / "mic.wav"
        self._system_path = session_dir / "system.wav"
        self._pa = None  # 共有 PyAudio インスタンス (start で生成、stop で終了)

    @property
    def mic_path(self) -> Path:
        return self._mic_path

    @property
    def system_path(self) -> Path:
        return self._system_path

    def start(
        self,
        mic_index: int | None = None,
        system_index: int | None = None,
        mic_on_chunk: Callable | None = None,
        system_on_chunk: Callable | None = None,
        mic_mute_check: Callable[[], bool] | None = None,
        system_mute_check: Callable[[], bool] | None = None,
    ) -> None:
        if mic_index is None:
            mic_index = find_default_mic_index()
        if system_index is None:
            system_index = find_default_loopback_index()
        # 解決した info dict を渡す方式 (index 単独だと PyAudio インスタンス再enum で
        # ずれる可能性があるため)
        mic_info = resolve_device_info(mic_index) if mic_index is not None else None
        sys_info = resolve_device_info(system_index) if system_index is not None else None
        if mic_info is None and sys_info is None:
            raise RuntimeError(
                f"no usable input devices (mic_index={mic_index}, system_index={system_index}). "
                f"指定したデバイスが録音不可、もしくは存在しない可能性があります。"
            )
        # mic と system のスレッドで PyAudio を共有 + open 時に排他 lock
        # (2インスタンス並列 open で WASAPI が誤動作する環境がある)
        import pyaudiowpatch as pyaudio
        self._pa = pyaudio.PyAudio()
        open_lock = threading.Lock()
        self._open_lock = open_lock  # stop() の terminate でも使う (close と直列化)
        if mic_info is not None:
            self._mic = _ChannelRecorder(
                mic_info, self._mic_path, self._sample_rate,
                on_chunk=mic_on_chunk, pyaudio_instance=self._pa,
                open_lock=open_lock, mute_check=mic_mute_check,
            )
            self._mic.start()
        if sys_info is not None:
            self._sys = _ChannelRecorder(
                sys_info, self._system_path, self._sample_rate,
                on_chunk=system_on_chunk, pyaudio_instance=self._pa,
                open_lock=open_lock, mute_check=system_mute_check,
            )
            self._sys.start()

    def stop(self) -> dict[str, Path | None]:
        """両ストリームを停止し、生成された wav パス (失敗時は None) を返す。"""
        result: dict[str, Path | None] = {"mic": None, "system": None}
        if self._mic is not None:
            self._mic.stop()
            if self._mic.error is None and self._mic_path.exists():
                result["mic"] = self._mic_path
        if self._sys is not None:
            self._sys.stop()
            if self._sys.error is None and self._system_path.exists():
                result["system"] = self._system_path
        # 共有 PyAudio を最後に terminate (両スレッドが完全停止し close を終えた後)。
        # close と同じ lock を取り、native 層での terminate/close 競合を避ける。
        # ただし、いずれかの capture スレッドがまだ stream.read 内で生きている場合に
        # terminate を呼ぶと native segfault でサーバプロセスごと落ちる。その場合は
        # terminate を呼ばず PyAudio をリーク (warn) させる方が、SIGSEGV より遥かに安全。
        if self._pa is not None:
            still_alive = (self._mic is not None and self._mic.alive) or \
                          (self._sys is not None and self._sys.alive)
            if still_alive:
                import sys
                print("[recorder] WARNING: a capture thread did not stop; "
                      "skipping PyAudio.terminate() to avoid a native crash",
                      file=sys.stderr, flush=True)
            else:
                lock = getattr(self, "_open_lock", None)
                # Best-effort terminate: stop() must complete and clear _pa even
                # if PyAudio.terminate() raises (it has been observed to surface
                # WASAPI driver hiccups). Leaking is safer than crashing.
                with contextlib.suppress(Exception):
                    if lock is not None:
                        with lock:
                            self._pa.terminate()
                    else:
                        self._pa.terminate()
            self._pa = None
        return result
