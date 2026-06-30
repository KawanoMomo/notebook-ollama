# Smoke Report: `recording` extras optional

- **Date**: 2026-06-30
- **Branch**: `feat/recording-extras-optional`
- **Verdict**: **PASS**
- **API**: `uv run uvicorn apps.api.main:app --port 8765 --host 127.0.0.1`
- **SPA**: `apps/web/dist/` (built via `npm run build`, served by FastAPI)
- **Diff under test**: `apps/api/dependencies.py`, `apps/api/routers/recordings.py`

## Evidence files (absolute paths)

- `E:\00_Git\10_NotebookOllama\docs\eval\2026-06-30-recording-extras-optional\s1-home.png`
- `E:\00_Git\10_NotebookOllama\docs\eval\2026-06-30-recording-extras-optional\s2-base-install-boots.png`
- `E:\00_Git\10_NotebookOllama\docs\eval\2026-06-30-recording-extras-optional\s2-home-dom.yml`
- `E:\00_Git\10_NotebookOllama\docs\eval\2026-06-30-recording-extras-optional\s2-recordings-503.json`
- `E:\00_Git\10_NotebookOllama\docs\eval\2026-06-30-recording-extras-optional\s2-audio-devices-503.json`
- `E:\00_Git\10_NotebookOllama\docs\eval\2026-06-30-recording-extras-optional\s2-uvicorn-base.log`
- `E:\00_Git\10_NotebookOllama\docs\eval\2026-06-30-recording-extras-optional\s3-extras-restored.png`
- `E:\00_Git\10_NotebookOllama\docs\eval\2026-06-30-recording-extras-optional\s3-health-200.json`
- `E:\00_Git\10_NotebookOllama\docs\eval\2026-06-30-recording-extras-optional\s3-audio-devices-200.json`
- `E:\00_Git\10_NotebookOllama\docs\eval\2026-06-30-recording-extras-optional\s3-recordings-200.json`
- `E:\00_Git\10_NotebookOllama\docs\eval\2026-06-30-recording-extras-optional\s3-stop-200.json`
- `E:\00_Git\10_NotebookOllama\docs\eval\2026-06-30-recording-extras-optional\s3-uvicorn-extras.log`

## Pre-flight

| Step | Result |
|---|---|
| `uv sync` (drop recording extras) | OK — 24 packages uninstalled including `soundfile`, `faster-whisper`, `sherpa-onnx*`, `pyaudiowpatch`, `scipy`, `webrtcvad-wheels`, `ctranslate2`, `nvidia-cublas-cu12`, `nvidia-cudnn-cu12` |
| `uv run uvicorn ...` (base) | OK — port 8765 responds 200, **boot succeeded without recording extras** (master baseline would crash on `from core.recording.recording_pipeline import RecordingPipeline` at module import) |
| `uv sync --extra recording` (restore) | OK — packages restored |
| `cd apps/web && npm run build` | OK — `built in 22.10s`, `Wrote site to "dist"` |
| `mkdir -p docs/eval/2026-06-30-recording-extras-optional` | OK |

## Scenarios

### S1 — App boots + home renders + 0 console errors (extras present)
- Navigate `http://127.0.0.1:8765/` → 200, `Notebook Ollama` title.
- Home page lists 14 notebook tiles, "新規ノートブック" button visible.
- Playwright `browser_console_messages(error)`: **0 errors, 0 warnings**.
- Screenshot: `s1-home.png`.
- **Result: PASS**

### S2 — Recording extras absent (most critical)
- State: extras uninstalled via `uv sync` (no `--extra recording`).
- Uvicorn boot log includes the documented degrade message:
  > `recording extras not installed (soundfile); recording endpoints will return 503. Run` `` `uv sync --extra recording` `` `to enable.`
  Application startup completes normally.
- `GET /api/health` → **200** `{"status":"ok","sqlite":true,"endpoint":"http://localhost:11434","version":"0.1.0"}`
- `GET /` → **200** (SPA served, home renders behind first-visit crash-report consent modal — confirms boot, no error UI).
- `POST /api/notebooks/01KW9P17H2BFM5YFX8N4W7GK8H/recordings` →
  **503** `{"detail":"recording extras not installed; run` `` `uv sync --extra recording` `` `to enable"}`
  (matches `_RECORDING_EXTRA_HINT` exactly.)
- `GET /api/audio-devices` →
  **503** `{"detail":"recording extras not installed: No module named 'pyaudiowpatch'"}`
  (this endpoint guards by `pyaudiowpatch` import at module level — also degrades gracefully.)
- Playwright `browser_console_messages(error)`: **0 errors**.
- Screenshot: `s2-base-install-boots.png`. DOM dump: `s2-home-dom.yml`.
- **Result: PASS** — proves the optional pattern: base install boots, recording endpoints respond 503 with the hint instead of crashing the process.

### S3 — Extras restored
- State: `uv sync --extra recording` re-installed all heavy deps.
- Uvicorn boot log is **clean** — no "recording extras not installed" warning.
- `GET /api/health` → **200**.
- `GET /api/audio-devices` → **200** with real device list (Razer Seiren Mini, Steam Streaming Mic, loopback devices…).
- `POST /api/notebooks/.../recordings` → **200** with `recording_id`, `source_id`, `status=recording`, `live_caption=true` — full happy path works.
- `POST /api/notebooks/.../recordings/{rid}/stop` → **200** with `status=processing` and `paths.mic` / `paths.system` WAV file locations.
- `POST /api/notebooks/.../recordings/{src}/cancel` → **200** with `cancelled=true` (cleanup of the smoke recording so we don't leak a background job).
- SPA notebook detail page renders recording UI (録音 source, ライブ字幕 toggle, recording badge).
- Playwright `browser_console_messages(error)`: **0 errors**.
- Screenshot: `s3-extras-restored.png`.
- **Result: PASS**

### S4 — Console errors throughout
- Three Playwright navigations: `/` (S2 base), `/` (S1 extras), `/notebooks/<id>` (S3 extras).
- All three: `browser_console_messages(level=error)` = **0 errors, 0 warnings**.
- **Result: PASS**

## Summary table

| # | Scenario | Result |
|---|---|---|
| S1 | Home renders, extras present | PASS |
| S2 | Base install boots, recording endpoints 503 with hint | PASS |
| S3 | Extras restored, recording endpoints fully functional | PASS |
| S4 | 0 console errors across all navigations | PASS |

## Notes

- The 503 path was verified for both `POST /api/notebooks/{id}/recordings` (guarded by the new `_require_recording_pipeline` helper) and `GET /api/audio-devices` (degrades earlier via `pyaudiowpatch` import-time catch at the router module level — already present in `apps/api/routers/recordings.py`). Both return the same `uv sync --extra recording` hint pattern.
- The `from __future__ import annotations` in `apps/api/dependencies.py` lets `RecordingPipeline | None` work without a runtime import via `TYPE_CHECKING`, so no quoting hack is needed (matches the inline comment).
- One stale UI artifact noticed in S3: the recording badge in the source list briefly read `RECORDING ready` even though the start→stop→cancel sequence had completed. This is unrelated to the optional-extras change (same behavior would happen with the recording session anywhere); flagged for awareness only — not a regression.

## Teardown

- Killed the extras-mode uvicorn (PID 243 / child 48728).
- Left environment with `uv sync --extra recording` applied so the rest of the workflow has the full env.
