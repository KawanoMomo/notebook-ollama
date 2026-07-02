# Sprint 9 — クラッシュレポート & お知らせ/フィードバックハブ 仕上げ

- 期間: 2026-06-29
- 関連 plan: [`docs/superpowers/plans/2026-06-28-crash-report-feedback-hub.md`](../../superpowers/plans/2026-06-28-crash-report-feedback-hub.md) §Sprint 9
- 関連 spec: [`docs/specs/2026-06-28-crash-report-feedback-hub-design.md`](../../specs/2026-06-28-crash-report-feedback-hub-design.md)
- PR: #6 (`feat/crash-report-feedback-hub`)

## スコープ

Sprint 1〜8 で実装した「クラッシュレポート」「お知らせタブ」「不具合タブ」「ご意見タブ」「設定セクション」「初回オプトイン」を最終仕上げするスプリント。

- Task 9.1: Playwright E2E 5 シナリオ (spec §11.3)
- Task 9.2: ヘッダ Megaphone アイコンサイズ最終確定
- Task 9.3: README / 仕様オープン項目 / plan 完了マーク追記 (本ドキュメント)

## サマリ

Sprint 1〜8 のすべてのバックエンド/フロントエンドモジュールが TDD で GREEN になり、各 Sprint の視覚ゲートも個別レポートで PASS 済み。Sprint 9 では仕上げとして E2E と最終アイコンサイズ・ドキュメントを揃える。

### 完了モジュール一覧 (Sprint 1〜8)

**バックエンド (`core/crash_reporter/` + `core/feedback_hub/` + `apps/api/routers/`)**

- `redactor` / `fingerprint` / `hardware` — Sprint 1
- `pending_store` / `reported_store` / `formatter` / `prefill_url` — Sprint 2
- `collector` (traps 統合) / `crash` ルータ / `feedback_hub` ルータ / `DomainError` 階層 — Sprint 3
- `lifecycle.py` (unclean shutdown 検知 + `running.lock` + psutil) — Sprint 4

**フロントエンド (`apps/web/src/lib/`)**

- `AppHeader` Megaphone / `FeedbackHubDrawer` / 3 タブ (`NoticesTab` / `BugReportTab` / `FeedbackTab`) — Sprint 5
- `NoticesTab` の localStorage 既読管理 + 未読ドット — Sprint 6
- `BugReportTab` + 設定セクション + `OptInDialog` — Sprint 7
- `FeedbackTab` のスクショ機能 (html2canvas) + プリフィル URL — Sprint 8

## 視覚ゲート (Sprint 別レポート)

各 Sprint の Evaluator スクショは下記ディレクトリに保存。Sprint 9 は本ドキュメントが入口。

- [Sprint 5 — Drawer 枠 + 即時モーダル + プレビュー](../2026-06-28-feedback-hub-sprint5/) — `s1-header-megaphone.png` / `s2-drawer-tab1-news.png` / `s4-crash-detection-modal.png` / `s5a-preview-dialog-loaded.png` / `s6-focus-trap.png` 他
- [Sprint 6 — お知らせタブ + 未読ドット](../2026-06-29-feedback-hub-sprint6/) — `s1-notices-tab-initial.png` / `s2-notices-after-click.png` / `s3-notices-after-reload.png` / `s4a-header-with-dot.png` / `s4b-header-without-dot.png` / `s5-typography-check.png` 他
- [Sprint 7 — 不具合タブ + 設定 + オプトイン](../2026-06-29-feedback-hub-sprint7/) — `s1-bugs-tab-empty.png` / `s2-bugs-tab-with-pending.png` / `s5-settings-crashreport-section.png` / `s6-disabled-no-modal.png` / `s8a-optin-dialog.png` / `s8b-optin-after-enable.png` 他
- [Sprint 8 — ご意見タブ + スクショ](../2026-06-29-feedback-hub-sprint8/) — `s1-feedback-tab-initial.png` / `s2a-kind-feature.png` / `s4a-thumbs-up.png` / `s5-screenshot-captured.png` / `s7-prefill-url-tab.png` 他

## 仕様準拠の主要ポイント

- **完全ローカル**: 自動送信は一切行わず、ユーザーがプレビューで内容を編集してからブラウザの別タブで GitHub Issue 起票 URL を開く
- **PAT 埋め込みなし**: 公開アプリへ GitHub トークンを埋め込まない。すべてユーザーの GitHub アカウントで完結
- **プライバシ合意モデル**: UI 上で「送信される/されない」を一切宣言せず、プレビュー画面で実際に送信される内容を目視確認させる (user memory `feedback_no_data_guarantee_in_ui` に準拠)
- **ホワイトリスト方式の Redactor**: ホスト名・ファイルパス・RAG チャンク・ドキュメント本文は収集対象から除外
- **fingerprint による重複抑制**: スタックトレース SHA1 で同一バグの重複起票を自動防止
- **既定 OFF**: クラッシュレポート機能は既定で無効。設定または初回エラー時の `OptInDialog` で同意してから有効化
- **8KB プリフィル URL 制限対応**: GitHub Issue URL が 8KB を超える場合、`body` を段階的に短縮 (`prefill_url.py`)

## 最終ゲート (Sprint 9)

下記が Sprint 9 commit 時点ですべて PASS であることをオーケストレータが最終確認。

1. `uv run pytest -q` — backend 全 GREEN
2. `cd apps/web && npm run check` — 0 errors
3. `cd apps/web && npm run build` — 成功
4. `cd apps/web && npx playwright test feedback-hub` — 5 シナリオ PASS
5. Sprint 5〜8 の視覚ゲートを通し直し、final commit 状態でも崩れていない
