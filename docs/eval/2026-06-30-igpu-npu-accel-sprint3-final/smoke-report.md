# Sprint 3 Final Ruff Cleanup — Smoke Report

## 判定: PASS
## 実行日時: 2026-06-30 03:17 (JST)
## スコープ: Sprint 3 ruff/lint final cleanup の回帰確認 (30+ files, mostly tests + apps/api/main.py truststore imports)

## 環境
- Backend: `uv run uvicorn apps.api.main:app --port 8765 --host 127.0.0.1` (PID 30180)
- Frontend: `npm run build` → `dist/` (svelte adapter-static, served by uvicorn at `/`)
- /api/health: `{"status":"ok","sqlite":true,"endpoint":"http://localhost:11434","version":"0.1.0"}`

## 証拠ファイル一覧 (絶対パス)
- E:\00_Git\10_NotebookOllama\docs\eval\2026-06-30-igpu-npu-accel-sprint3-final\ss1-home.png
- E:\00_Git\10_NotebookOllama\docs\eval\2026-06-30-igpu-npu-accel-sprint3-final\ss2-accel.png
- E:\00_Git\10_NotebookOllama\docs\eval\2026-06-30-igpu-npu-accel-sprint3-final\api-response.json
- E:\00_Git\10_NotebookOllama\docs\eval\2026-06-30-igpu-npu-accel-sprint3-final\ss4-notebook.png

## スモーク結果

### SS1: App boots + home page renders + 0 console errors — PASS
- URL: http://127.0.0.1:8765/
- 観測: `<h1>ノートブック</h1>` + `新規ノートブック` button + 14 件のノートブックカード描画
- console.error: 0
- 証拠: ss1-home.png

### SS2: /settings ▸ アクセラレーション panel renders — PASS
- URL: http://127.0.0.1:8765/settings (アクセラレーション tab クリック後)
- 観測項目:
  - 検出ハードウェア: CPU `12th Gen Intel(R) Core(TM) i9-12900KF`, CUDA dGPU `NVIDIA GeForce RTX 2080 Ti` VRAM 11264 MiB, DirectML 未検出
  - 選択バックエンド: `faster-whisper-cuda` / `sherpa-onnx-cpu` / `ollama-cuda` / `ollama-bge-m3-cpu`
  - 選定理由テキスト (STT/DIARIZE/LLM/TEXT_EMBED) 描画
  - 状態: `Phase 1 実装可能 ✓`, 再検出ボタン描画
  - Phase 1 制限ノート (Intel iGPU/NPU + AMD Ryzen AI は Phase 2) 描画
- console.error: 0
- 証拠: ss2-accel.png

### SS3: GET /api/settings/acceleration → 200 — PASS
- HTTP 200, JSON 構造:
  - `hw_profile.cpu_brand` = "12th Gen Intel(R) Core(TM) i9-12900KF"
  - `hw_profile.cuda` = true, `hw_profile.dgpu` = "NVIDIA GeForce RTX 2080 Ti", `vram_mb` = 11264
  - `hw_profile.igpu` = null, `npu` = null, `ryzen_ai_gen` = null, `openvino_devices` = [], `has_directml` = false
  - `backend_plan.stt_id` = "faster-whisper-cuda", `diarize_id` = "sherpa-onnx-cpu", `llm_id` = "ollama-cuda", `text_embed_id` = "ollama-bge-m3-cpu"
  - `is_phase1_implementable` = true
- 証拠: api-response.json

### SS4: Notebook detail + RecordingControls + Chat panel render — PASS
- URL: http://127.0.0.1:8765/notebooks/01KS5ASTT6FA1YQSE12B38P7X7
- 観測:
  - `<h1>QSPI</h1>` 描画
  - モデルセレクト (qwen3:32b, gpt-oss:20b 等) 描画
  - RecordingControls: `<button aria-label="録音">` + `<button aria-label="録音を再生">` 検出
  - ソース一覧 3 件 (recording / pdf 52p / pdf 943p) 描画
  - Chat panel: `<textarea placeholder="質問を入力（Cmd/Ctrl+Enter で送信）">` + `送信` button 検出
- console.error: 0
- 証拠: ss4-notebook.png

## メトリクス
- console.error 件数 (全シナリオ合計): 0
- HTTP 失敗件数: 0
- AC PASS 比率: 4/4

## 結論
Sprint 3 最終 ruff cleanup (truststore import 移動を含む) はランタイム回帰なし。
- バックエンドは起動し /api/health = ok、/api/settings/acceleration = 200 JSON
- フロントエンドは home / settings(アクセラレーション panel) / notebook detail いずれも描画 OK
- 全画面で console.error = 0、RecordingControls と Chat textarea も従来通り検出

verdict = **PASS**
