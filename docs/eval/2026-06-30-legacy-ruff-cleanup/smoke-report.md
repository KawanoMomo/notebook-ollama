# Smoke Report — legacy-ruff-cleanup (152 fixes)

## 判定: PASS
## 実行日時: 2026-06-30 22:30 JST (re-verification run)
## ブランチ: chore/legacy-ruff-cleanup
## 目的: ruff 152 fixes が起動チェイン (apps/api/main.py + dependencies.py + routers) と SPA ビルド (apps/web) に regression を持ち込んでいないことの実機確認

## 環境
- API: `uv run uvicorn apps.api.main:app --port 8765 --host 127.0.0.1` (背景プロセス、PID は scratchpad/uvicorn.pid に保存)
- FE: `cd apps/web && npm run build` → `apps/web/dist/` を FastAPI が StaticFiles でマウント
- FE build: 成功 (Vite "built in 31.38s", 0 errors)
- Health: `GET /` → 200 (SvelteKit static index)

## 証拠ファイル一覧 (絶対パス)
- E:\00_Git\10_NotebookOllama\docs\eval\2026-06-30-legacy-ruff-cleanup\s1-home.png
- E:\00_Git\10_NotebookOllama\docs\eval\2026-06-30-legacy-ruff-cleanup\s2-settings.png
- E:\00_Git\10_NotebookOllama\docs\eval\2026-06-30-legacy-ruff-cleanup\s3-notebook.png
- E:\00_Git\10_NotebookOllama\docs\eval\2026-06-30-legacy-ruff-cleanup\s4-chat.png
- E:\00_Git\10_NotebookOllama\docs\eval\2026-06-30-legacy-ruff-cleanup\console-errors.log

(前回run分の ss1-ss4.png / console-all.log / uvicorn.log も同ディレクトリに保存済み — 同一結論を独立に裏付け)

## 受入条件別の判定

### S1: App boots + home renders + 0 console errors
- 結果: PASS
- 証拠: s1-home.png
- 観測:
  - `GET /` → 200, `<title>Notebook Ollama</title>`
  - ヘッダ「Notebook Ollama」+「設定」リンク、見出し「ノートブック」、新規ノートブックボタン、ノートブックカード15枚 (E2E Test Notebook, QSPI, 雑談, mute-e2e-verify×3, AI関係, scope-test, s5-verify, rec-pipeline-test, rec-smoke×2 ほか) が描画される

### S2: /settings — 全6セクションが描画される
- 結果: PASS
- 証拠: s2-settings.png
- 操作と検証 (nav ボタンを順次クリックし `main h3` を都度評価):
  - 「モデル・Ollama」 → `main h3` = "モデル・Ollama"
  - 「生成・検索」 → `main h3` = "生成"
  - 「プロンプト」 → `main h3` = "プロンプト"
  - 「音声・録音」 → 初期表示、デバイス2件・Whisperモデル・話者分離・保存形式までフォーム描画
  - 「ストレージ」 → `main h3` = "ストレージ"
  - 「利用可能モデル」 → `main h3` = "利用可能モデル"
- いずれのセクション切替もエラーなく対応する h3 / フォームが描画

### S3: 既存ノートブック詳細 — RecordingControls + Chat panel が描画
- 結果: PASS
- 証拠: s3-notebook.png
- URL: /notebooks/01KW9P17H2BFM5YFX8N4W7GK8H (E2E Test Notebook)
- 観測:
  - h2 = "E2E Test Notebook"
  - 「すべてのソース 1 / 1」、「録音」ボタン、`recording  ready` ステータス (RecordingControls 健在)
  - 「ソースガイド」「ADR」「送信」ボタン群
  - 中央ペインに ChatInput textarea

### S4: ChatInput renders + typing が動作
- 結果: PASS
- 証拠: s4-chat.png
- 観測: `main textarea` 1件、placeholder = "質問を入力（Cmd/Ctrl+Enter で送信）"、「送信」ボタン存在
- 操作: `fill('smoke test: ruff cleanup did not break ChatInput')` 成功、ChatInput がコントロール可能な状態で生存

### S5: S1-S4 横断 console error チェック
- 結果: PASS
- 証拠: console-errors.log → `Total messages: 0 (Errors: 0, Warnings: 0)`
- `browser_console_messages(level=error, all=true)` 結果: import 失敗 / module not found / 挙動変化に紐づくエラー 0件

### S6: Backend smoke (`/api/notebooks`, `/api/settings`)
- 結果: PASS
- 証拠: 下記 curl 結果
  - `curl /api/notebooks` → HTTP 200, JSON 配列 (先頭: E2E Test Notebook 01KW9P17H2BFM5YFX8N4W7GK8H)
  - `curl /api/settings` → HTTP 200
- これにより `apps/api/main.py → dependencies.py → routers (notebooks, settings) → core` の import チェインが ImportError / AttributeError なく成立していることを確認

## console.error 件数: 0
## network 失敗件数: 0 (5xx/4xx 観測なし)

## 総合判定の根拠
ruff 152件の自動整形/手動修正後も:
1. FE 本番ビルド 成功 (vite 31.38s, 0 errors)
2. FastAPI 起動成功 (`/`, `/api/notebooks`, `/api/settings` すべて 200)
3. SPA ルーティング: home / settings(全6セクション) / notebook detail すべて renders
4. RecordingControls / ChatInput / Send button といった重要コンポーネントが生存
5. console error 0件

ruff cleanup を安全にマージしてよい。

## ティアダウン
- uvicorn background プロセスは smoke 完了後に kill
