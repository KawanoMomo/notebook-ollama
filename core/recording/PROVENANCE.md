# Provenance & vendoring audit

Modules under `core/recording/` are vendored from the author's own MIT project
`04_MeetingTranscriber` (private: KawanoMomo/meeting-transcriber). Each file was
audited for embedded third-party source before inclusion; third-party libraries
and STT/diarization models are dependencies/assets (not embedded) and are
declared in `pyproject.toml` (`recording` extra) / `LICENSE-THIRDPARTY.md`.

| File | Audit verdict | Third-party imports (deps, not embedded) |
|---|---|---|
| recorder.py | original_self_authored — safe | pyaudiowpatch, numpy |

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
