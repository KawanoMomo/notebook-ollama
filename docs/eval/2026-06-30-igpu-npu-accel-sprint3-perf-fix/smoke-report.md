# Smoke Report — iGPU/NPU Accel Sprint 3 Perf Fix

## Verdict: PASS
## Run: 2026-06-30 08:29 JST

## Evidence (absolute paths)
- E:\00_Git\10_NotebookOllama\docs\eval\2026-06-30-igpu-npu-accel-sprint3-perf-fix\ss1-home.png
- E:\00_Git\10_NotebookOllama\docs\eval\2026-06-30-igpu-npu-accel-sprint3-perf-fix\ss2-accel.png
- E:\00_Git\10_NotebookOllama\docs\eval\2026-06-30-igpu-npu-accel-sprint3-perf-fix\ss3-notebook.png

## Pre-flight
- uvicorn `apps.api.main:app` on `127.0.0.1:8765` — `/api/health` returned `{"status":"ok","sqlite":true,"endpoint":"http://localhost:11434","version":"0.1.0"}` (PID 36876).
- `npm run build` (apps/web) — built in 20.77s, adapter-static wrote site to `dist`.
- vite dev (`npm run dev --port 5173`) — ready in 770ms (a11y warnings only, no errors).

## Scenarios

### SS1 — App boots + home + 0 console errors — PASS
- URL: http://localhost:5173/
- Title: Notebook Ollama. Header (Notebook Ollama link, 設定 link), `ノートブック` heading, `新規ノートブック` button, notebook list rendered with multiple existing notebooks.
- `browser_console_messages level=error` → 0 errors.
- Evidence: ss1-home.png

### SS2 — /settings ▸ アクセラレーション panel renders — PASS
- URL: http://localhost:5173/settings
- Waited for text `アクセラレーション` — visible.
- `browser_console_messages level=error` → 0 errors.
- Evidence: ss2-accel.png

### SS3 — Notebook detail + RecordingControls + Chat — PASS
- URL: http://localhost:5173/notebooks/01KW9P17H2BFM5YFX8N4W7GK8H
- Notebook heading `E2E Test Notebook` rendered; model combobox present; sidebar with `追加` and `録音` buttons (RecordingControls), `ライブ字幕` switch; main chat area with `質問を入力（Cmd/Ctrl+Enter で送信）` textbox and `送信` button (Chat).
- `browser_console_messages level=error` → 0 errors.
- Evidence: ss3-notebook.png

## console.error total: 0
## network failures: not collected (no failure surfaced during scenario execution)

## Notes
- Perf-fix-touched code paths (production + perf harness) did not regress the dev server boot, the home page render, the settings/アクセラレーション panel, or the notebook detail surface (RecordingControls + Chat).
- a11y warnings from vite (autofocus, dialog tabindex) are pre-existing and unrelated to the perf fix.
