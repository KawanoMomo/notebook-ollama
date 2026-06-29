# Sprint 2 Smoke Report — igpu-npu-accel (BackendPlanner + BackendPlan + BACKEND_IDS)

- 判定: **PASS**
- 実行日時: 2026-06-30 00:43 JST
- ブランチ: `feat/igpu-npu-accel`
- HEAD (commit): `c7d3512` (Sprint 1) + uncommitted Sprint 2 working tree
  - 新規ファイル: `core/accel/backend_ids.py`, `core/accel/plan.py`, `core/accel/planner.py`
  - 新規テスト: `tests/unit/test_backend_ids.py`, `tests/unit/test_backend_plan.py`, `tests/unit/test_planner.py`, `tests/integration/test_accel/test_planner_e2e.py`
- 環境: Windows 11, RTX 2080 Ti, dev server `uv run uvicorn apps.api.main:app --port 8765`
- 環境変数: `NOTEBOOK_OLLAMA_SKIP_ACCEL_PROBE=1` (Sprint 1 で導入。probe を抑止して起動時間を短縮)

Sprint 2 は **純粋ドメインの追加のみ**（API endpoint / UI 一切ナシ）。本スモークは「新規 import が ASGI app の起動を壊していないこと」と「既存の UI / API が後退していないこと」をエビデンス付きで確認する。

## 証拠ファイル一覧（絶対パス）

- `E:\00_Git\10_NotebookOllama\docs\eval\2026-06-30-igpu-npu-accel-sprint2\ss1-home.png`
- `E:\00_Git\10_NotebookOllama\docs\eval\2026-06-30-igpu-npu-accel-sprint2\ss2-settings.png`
- `E:\00_Git\10_NotebookOllama\docs\eval\2026-06-30-igpu-npu-accel-sprint2\ss3-notebook.png`
- `E:\00_Git\10_NotebookOllama\docs\eval\2026-06-30-igpu-npu-accel-sprint2\smoke-report.md`（本ファイル）

## シナリオ別判定

### SS1: アプリ起動 / ホーム描画 / コンソール clean — PASS

- `GET http://127.0.0.1:8765/` → 200 OK, `<title>Notebook Ollama</title>`。
- ノート一覧（heading "ノートブック" + 「新規ノートブック」ボタン + 15 件のノートカード）が描画。
- `browser_console_messages(warning)` → Total messages: 0 (Errors: 0, Warnings: 0)。
- 証拠: `ss1-home.png` (88KB, full-page)。

### SS2: 設定画面ロード / 全セクション描画 — PASS

- `GET /settings` → 200 OK。デフォルトで「音声・録音」セクション表示。
- 以下の 6 セクションを順次クリック → いずれも `[ref]` 構造が描画され、コンソールエラー 0:
  - LLM/生成 > モデル・Ollama (e17)
  - LLM/生成 > 生成・検索 (e21)
  - LLM/生成 > プロンプト (e24)
  - システム > ストレージ (e34)
  - システム > 利用可能モデル (e37) — Ollama から 19 モデル取得して `<table>` レンダリング（bge-m3, qwen3:32b, gpt-oss:20b-128k 等）
  - 入力/取り込み > 音声・録音 (e29) — マイク 25 デバイス検出、Whisper モデル/compute_type/話者分離設定描画
- 各クリック後の `browser_console_messages(warning)` → Errors: 0 / Warnings: 0 を維持。
- 証拠: `ss2-settings.png` (177KB, 音声・録音セクション展開状態)。

### SS3: ノート詳細ロード / RecordingControls + Chat 描画 — PASS

- `GET /notebooks/01KVN2Z0PDTJMCK4KBQMDP1D44` (AI関係) → 200 OK。
- ヘッダ「AI関係」, モデルセレクタ（既定 gpt-oss:20b + 17 件のオプション）描画。
- 左ペイン: ソース一覧（2 件）+ 「追加」「録音」ボタン + ライブ字幕 switch。
- 中央: チャット入力 (`textbox "質問を入力（Cmd/Ctrl+Enter で送信）"` + 送信ボタン)。
- 右ペイン: 引用パネル。
- バックエンド API 呼び出し（SS3 中に観測）:
  - `GET /api/prompts` → 200
  - `GET /api/notebooks/{id}` → 200
  - `GET /api/notebooks/{id}/sources` → 200
  - `GET /api/models` → 200
  - `GET /api/settings` → 200
  - `GET /api/stats` → 200
- `browser_console_messages(warning)` → Errors: 0 / Warnings: 0。
- 証拠: `ss3-notebook.png` (65KB, full-page)。

### SS4: バックエンド import smoke — PASS

コマンド:
```bash
NOTEBOOK_OLLAMA_SKIP_ACCEL_PROBE=1 uv run python -c \
  "from core.accel.planner import BackendPlanner; \
   from core.accel.plan import BackendPlan; \
   from core.accel.backend_ids import BACKEND_IDS; \
   from core.accel.probe import HardwareProbe; \
   hw = HardwareProbe().run(); \
   plan = BackendPlanner().plan(hw); \
   print(plan)"
```

stdout（無加工）:
```
stt=faster-whisper-cpu llm=ollama-cuda text_embed=ollama-bge-m3-cpu diarize=sherpa-onnx-cpu
reason=STT: no GPU/NPU acceleration detected -> faster-whisper-cpu; DIARIZE: diarizer is cpu-only in v1 -> sherpa-onnx-cpu; LLM: no GPU detected -> ollama-cuda (auto-degrades to CPU); TEXT_EMBED: no Intel iGPU/NPU detected -> ollama-bge-m3-cpu
```

- exit 0、ImportError 0、ValueError 0（`BackendPlan.__post_init__` の id 検証も通過）。
- 注: `NOTEBOOK_OLLAMA_SKIP_ACCEL_PROBE=1` のため probe は CPU プロファイルを返している。実機 RTX 2080 Ti（CUDA）での routing 検証は Sprint 3 で probe 統合後に行う。

### SS5: Crash-report / Megaphone — SKIP

このブランチに該当機能は存在しない（Sprint 1 と同様）。

### SS6: コンソールエラー横断チェック — PASS

SS1〜SS3 を通じて `browser_console_messages` を 4 回サンプリング、いずれも:
```
Total messages: 0 (Errors: 0, Warnings: 0)
```
`core/accel/*` 由来のエラーは皆無。

## ネットワーク失敗件数

- 0 件（SS3 中のキャプチャ `/api/*` 計 6 req、全 200 OK）。
- ASGI 起動時に `/api/health` → 200 (`{"status":"ok","sqlite":true,"endpoint":"http://localhost:11434","version":"0.1.0"}`)。

## console.error 件数

- 0 件

## まとめ

| ID  | Scenario                          | Result | Evidence            |
|-----|-----------------------------------|--------|---------------------|
| SS1 | App boots / home renders / clean  | PASS   | ss1-home.png        |
| SS2 | Settings page / 全セクション      | PASS   | ss2-settings.png    |
| SS3 | Notebook detail (録音+チャット)   | PASS   | ss3-notebook.png    |
| SS4 | Backend import smoke              | PASS   | stdout（本文中）    |
| SS5 | Crash-report / Megaphone          | SKIP   | branch非該当        |
| SS6 | Console errors                    | PASS   | 4 サンプル全て 0/0  |

Sprint 2 の新規 import は ASGI app の起動も SvelteKit FE の挙動も後退させていない。
verdict = **PASS** (SS1-SS4+SS6 PASS, SS5 SKIP 許容)。

## 推定原因（FAILの場合）

該当なし。
