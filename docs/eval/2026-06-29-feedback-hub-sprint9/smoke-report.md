# Sprint 9 Final Smoke Report — Feedback Hub

- 判定: **PASS**
- 実行日時: 2026-06-29 21:29 JST
- Backend: `uv run uvicorn apps.api.main:app --port 8765 --host 127.0.0.1` (PID 42160)
- Frontend: `apps/web/dist/` (built via `npm run build`, served by FastAPI static mount)
- Browser: Playwright MCP (Chromium)

## 証拠ファイル (絶対パス)

- E:\00_Git\10_NotebookOllama\docs\eval\2026-06-29-feedback-hub-sprint9\ss1.png — Megaphone visible / drawer opens at 440px
- E:\00_Git\10_NotebookOllama\docs\eval\2026-06-29-feedback-hub-sprint9\ss2.png — お知らせ tab default, 2 seed notices
- E:\00_Git\10_NotebookOllama\docs\eval\2026-06-29-feedback-hub-sprint9\ss3.png — 不具合 tab empty state
- E:\00_Git\10_NotebookOllama\docs\eval\2026-06-29-feedback-hub-sprint9\ss4.png — ご意見 tab, 3 radio chips
- E:\00_Git\10_NotebookOllama\docs\eval\2026-06-29-feedback-hub-sprint9\ss5.png — /settings クラッシュレポート section with toggles
- E:\00_Git\10_NotebookOllama\docs\eval\2026-06-29-feedback-hub-sprint9\ss6.png — CrashDetectionModal mounted (S7 fix holds)
- E:\00_Git\10_NotebookOllama\docs\eval\2026-06-29-feedback-hub-sprint9\ss7.png — CrashPreviewDialog mounted
- E:\00_Git\10_NotebookOllama\docs\eval\2026-06-29-feedback-hub-sprint9\ss8.png — Everything closed, header dot/state correct

## シナリオ別判定

### SS1. Megaphone visible & drawer 440px — PASS
- 証拠: ss1.png
- DOM: `button[aria-label="お知らせ・フィードバック"]` exists in header
- After click: `[role="dialog"]` mounted; `getComputedStyle(dialog).width === "440px"` and `getBoundingClientRect().width === 440`

### SS2. お知らせ tab default with 2 seed notices — PASS
- 証拠: ss2.png
- DOM: tab list `[role="tablist"]` contains tabs `お知らせ / 不具合 / ご意見`; `お知らせ` has `aria-selected="true"` on initial open
- Panel contains 2 `<article>` entries:
  1. "クラッシュレポート & フィードバックハブを公開しました" (2026年6月28日)
  2. "リリースノート: PR #4 統合"

### SS3. 不具合 tab — empty state visible — PASS
- 証拠: ss3.png
- Pre-condition: cleared 19 leftover pending crashes from prior eval runs via `POST /api/crash/{id}/dismiss` loop (all returned 204)
- Verified `GET /api/crash/pending` returned 0 entries after dismissal
- After reload + tab click: panel text shows "未送信のレポートはありません" + 新規報告作成 CTA
- Selected tab: `不具合`

### SS4. ご意見 tab — 3 radiogroup chips visible — PASS
- 証拠: ss4.png
- `[role="radiogroup"]` present, 3 `[role="radio"]` items: `機能要望 / 使いにくさ / 感想`
- Form also exposes 本文 textarea, スクリーンショット attachment, 送信内容をプレビュー → CTA

### SS5. /settings → クラッシュレポート section visible with toggles — PASS
- 証拠: ss5.png
- Sidebar nav contains `クラッシュレポート` item; clicked it.
- Heading `クラッシュレポート` rendered with 2 toggles:
  - `クラッシュレポート機能を有効にする` (aria-checked=true)
  - `エラー発生時に自動でダイアログを表示` (aria-checked=true)

### SS6. Synthetic error → CrashDetectionModal mounts (S7 fix holds) — PASS
- 証拠: ss6.png
- Trigger: `window.dispatchEvent(new ErrorEvent('error', { error: new Error('S9-smoke-synthetic-…'), … }))`
- After 2s wait: `[data-testid*="crash"]` (CrashDetectionModal) present with content "⚠ エラーが発生しました FrontendError: S9-smoke-synthetic-… 今は送らない / 送信内容をプレビュー →"
- Confirms the Sprint 7 mount fix (modal renders top-level so it survives across page contexts) still holds.

### SS7. 送信内容をプレビュー → CrashPreviewDialog mounts — PASS
- 証拠: ss7.png
- Clicked "送信内容をプレビュー →" inside detection modal
- `[role="dialog"]` heading "送信内容のプレビュー" mounted with:
  - タイトル input
  - ラベル: `crash-auto`, `needs-triage`
  - 本文 (Markdown) editor
  - Actions: 却下 / クリップボードにコピー / GitHubで開く →

### SS8. Close everything → header dot/state correct — PASS
- 証拠: ss8.png
- 却下 dismissed preview AND detection modal in one click; no residual `[role="dialog"]` / crash modal in DOM
- Header `button[aria-label="お知らせ・フィードバック"]` still present
- 未読バッジ (generic "未読あり") absent — correct since all 2 seed notices were viewed earlier in flow and no new crashes pending
- No regression of header layout (megaphone + 設定 link both present)

## Console / Network

- `browser_console_messages level=error all=true` → 1 error
  - `Failed to load resource: the server responded with a status of 503 (Service Unavailable) @ http://127.0.0.1:8765/api/audio-devices:0`
  - Pre-existing environmental issue (no audio device enumeration available in this eval context). Unrelated to Sprint 9 feedback-hub work.
- No crash-report or feedback-hub related JS errors during the 8 scenarios.

## Network failure count: 1 (audio-devices 503 — pre-existing, unrelated)
## Console error count: 1 (same as above)
## Sprint 9 feature regression: 0

## 結論
8/8 シナリオ PASS。フィードバックハブ全体 (お知らせ / 不具合 / ご意見 / 設定 / クラッシュ検知 / プレビュー / クローズ後ヘッダ) に Sprint 9 変更による回帰なし。S7 で導入された CrashDetectionModal のトップレベル mount 修正も維持されている。

## TEARDOWN
- Browser closed via `mcp__playwright__browser_close` (Evaluator 規約)
- Uvicorn PID 42160 killed by caller (per PRE-FLIGHT TEARDOWN instruction)
