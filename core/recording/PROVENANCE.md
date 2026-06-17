# Provenance & vendoring audit

Modules under `core/recording/` are vendored from the author's own MIT project
`04_MeetingTranscriber` (private: KawanoMomo/meeting-transcriber). Each file was
audited for embedded third-party source before inclusion; third-party libraries
and STT/diarization models are dependencies/assets (not embedded) and are
declared in `pyproject.toml` (`recording` extra) / `LICENSE-THIRDPARTY.md`.

| File | Audit verdict | Third-party imports (deps, not embedded) |
|---|---|---|
| recorder.py | original_self_authored — safe | pyaudiowpatch, numpy |
| transcriber.py | original_self_authored — safe | faster_whisper, numpy |
| live_caption.py | original_self_authored — safe | webrtcvad, numpy (+ core.recording.agc) |
| agc.py | original_self_authored — safe | numpy (+ core.recording.levels) |
| levels.py | original_self_authored — safe | numpy |

## Local divergences from upstream (meeting-transcriber)

- **recorder.py — teardown-robustness fix (2026-06):** `recorder.py` now carries a
  LOCAL divergence from the meeting-transcriber source. A WASAPI system-loopback
  that yields no frames (e.g. nothing playing on output) previously caused the
  capture worker thread to block forever inside `stream.read(...)` and never
  re-check `_stop`; `stop()`'s `join(timeout=5)` then timed out and the subsequent
  shared `PyAudio.terminate()` ran while a `read` was in flight → native SIGSEGV
  (whole server process died). Fix has two parts: (1) an availability-gated read
  loop (`stream.get_read_available()` + 10 ms sleep) so an idle channel exits
  promptly on stop, and (2) a guarded `terminate()` in `Recorder.stop()` that
  skips `PyAudio.terminate()` (and logs a warning, leaking the instance) whenever
  any channel thread is still `alive`, since leaking PyAudio is far safer than a
  SIGSEGV. Recommend backporting the same fix to the upstream
  `04_MeetingTranscriber/app/core/recorder.py`.

- **Internal import rewrites (2026-06):** the vendored live-caption stack imported
  sibling modules via the upstream package path `app.core.*`. Every such import was
  rewritten to `core.recording.*`:
  - `live_caption.py`: `from app.core.agc import apply_gain, normalize_chunk`
    → `from core.recording.agc import apply_gain, normalize_chunk` (plus a docstring
    comment `app.core.transcriber.Transcriber` → `core.recording.transcriber.Transcriber`).
  - `agc.py`: `from app.core.levels import rms_db` → `from core.recording.levels import rms_db`.
  After rewriting, the 4 files contain ZERO `app.` references in executable code.

- **transcriber.py — `app`-package deps inlined (2026-06):** upstream
  `transcriber.py` depended on two non-`app.core.*` symbols that have no equivalent in
  10_NotebookOllama (which has no `app` package), so they were inlined locally rather
  than left as dangling imports:
  - `from app.models.schema import TranscriptSegment` → the single `TranscriptSegment`
    dataclass actually used is copied verbatim into `transcriber.py`.
  - `from app import _cuda_dll` → the stdlib-only CUDA (cuBLAS/cuDNN) DLL search-path
    registration is inlined as `_register_cuda_dll_dirs()` and run once at module import
    (before `WhisperModel` import), preserving upstream GPU behaviour. No-op on non-Windows
    / CPU-only / no-nvidia environments.
  When 10_NotebookOllama later defines its own transcript schema, these inlined copies
  should be reconciled with it.
