# Sprint 3 Fixes — Smoke Evaluation Report

## 判定: PASS
## 実行日時: 2026-06-30
## スコープ: factory.py + dependencies.py (test coverage + gateway sharing) + ruff hygiene
## 対象URL: http://127.0.0.1:8765 (uvicorn apps.api.main:app)

UI は変更されていない。本評価は「Sprint 3 のサーバ側修正が既存UIをリグレッションさせていない」ことを確認する smoke。

## 証拠ファイル一覧（絶対パス）
- E:\00_Git\10_NotebookOllama\docs\eval\2026-06-30-igpu-npu-accel-sprint3-fixes\ss1-home.png
- E:\00_Git\10_NotebookOllama\docs\eval\2026-06-30-igpu-npu-accel-sprint3-fixes\ss2-acceleration-panel.png
- E:\00_Git\10_NotebookOllama\docs\eval\2026-06-30-igpu-npu-accel-sprint3-fixes\ss4-notebook.png
- E:\00_Git\10_NotebookOllama\docs\eval\2026-06-30-igpu-npu-accel-sprint3-fixes\ss5-chat.png
- E:\00_Git\10_NotebookOllama\docs\eval\2026-06-30-igpu-npu-accel-sprint3-fixes\api-response.json
- E:\00_Git\10_NotebookOllama\docs\eval\2026-06-30-igpu-npu-accel-sprint3-fixes\network.txt
- E:\00_Git\10_NotebookOllama\docs\eval\2026-06-30-igpu-npu-accel-sprint3-fixes\uvicorn.log

## プリフライト
- uvicorn 起動: OK (PID 1084, port 8765)
- /api/health → 200 `{"status":"ok","sqlite":true,"endpoint":"http://localhost:11434","version":"0.1.0"}`
- `cd apps/web && npm run build` → ✓ built (server 10.58s, static dist 完了)

## シナリオ別判定

### SS1 — App boots + home page renders + 0 console errors: PASS
- /  → 200, ヘッダ「Notebook Ollama / 設定」、ノートブック一覧 (E2E Test Notebook ×2, 雑談, QSPI 他 全 15 件) を表示
- 証拠: ss1-home.png
- console errors: 0

### SS2 — Settings ▸ アクセラレーション パネル描画: PASS
- /settings へ遷移、左ナビ「アクセラレーション」クリック → パネル表示
- 検出ハードウェア セクション: CPU=12th Gen Intel(R) Core(TM) i9-12900KF / CUDA dGPU=NVIDIA GeForce RTX 2080 Ti (VRAM 11264 MiB) / DirectML=未検出
- 選択されたバックエンド セクション: STT=faster-whisper-cuda / Diarize=sherpa-onnx-cpu / LLM=ollama-cuda / Text Embed=ollama-bge-m3-cpu + 選定理由テキスト
- 状態 セクション: Phase 1 実装可能 ✓ + 再検出ボタン
- Phase 1 制限 セクション 表示
- read-only であることを確認 (combobox / input なし、ボタンは「再検出」のみ)
- 証拠: ss2-acceleration-panel.png

### SS3 — GET /api/settings/acceleration → 200 + 正常 JSON shape: PASS
- HTTP 200
- shape: `hw_profile{cpu_brand,cuda,dgpu,igpu,npu,vram_mb,ryzen_ai_gen,openvino_devices,has_directml}` + `backend_plan{stt_id,diarize_id,llm_id,text_embed_id,reason}` + `is_phase1_implementable`
- Sprint 3 ベースラインと同じキー構成
- 証拠: api-response.json

### SS4 — Notebook detail loads (gateway-sharing 修正のリグレッション確認): PASS
- /notebooks/01KVTGEMYYYB5PFYTP8JN45VH9 (「雑談」ノート) を直リンクで開く
- ヘッダ「雑談 + このノートのモデル combobox(18モデル)」描画
- 左サイドバー: ソース検索/追加/録音ボタン、ライブ字幕トグル、ソース一覧 (1/1)
- 中央: 要約タブ + Chat の質問入力 textbox + 送信ボタン (RecordingControls / Chat 復元 OK)
- 右サイドバー: 引用ペイン (空状態のプレースホルダ)
- 証拠: ss4-notebook.png

### SS5 — Chat panel renders: PASS
- ChatPanel: textbox「質問を入力（Cmd/Ctrl+Enter で送信）」+ 送信ボタン + 要約タブが正常描画
- (実際の送信は LLM 呼び出しで時間がかかるためスキップ — 描画のみ確認)
- 証拠: ss5-chat.png

### SS6 — Console errors check: PASS
- 全シナリオ通して `browser_console_messages(level=error, all=true)` → Total messages: 0 (Errors: 0, Warnings: 0)
- factory / accel / ollama 関連エラーなし

## ネットワーク統計
- /api/ 系リクエスト: 6 件 (/api/prompts, /api/notebooks/.../, /api/notebooks/.../sources, /api/models, /api/settings, /api/stats) すべて 200
- 4xx/5xx: 0 件
- 証拠: network.txt

## console.error 件数: 0
## network 失敗件数: 0

## 結論
Sprint 3 のサーバ側修正 (factory.py のテストカバレッジ追加 / dependencies.py の gateway 共有 / 旧 router の ruff 整備) は、既存 UI に対するリグレッションを発生させていない。Acceleration パネルは read-only かつ全セクション表示で正常、Notebook detail / Chat 経路も正常に復帰。
