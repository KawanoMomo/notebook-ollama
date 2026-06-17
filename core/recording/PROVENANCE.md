# Provenance & vendoring audit

Modules under `core/recording/` are vendored from the author's own MIT project
`04_MeetingTranscriber` (private: KawanoMomo/meeting-transcriber). Each file was
audited for embedded third-party source before inclusion; third-party libraries
and STT/diarization models are dependencies/assets (not embedded) and are
declared in `pyproject.toml` (`recording` extra) / `LICENSE-THIRDPARTY.md`.

| File | Audit verdict | Third-party imports (deps, not embedded) |
|---|---|---|
| recorder.py | original_self_authored — safe | pyaudiowpatch, numpy |
