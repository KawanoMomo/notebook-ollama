# 実機検証レポート: 発表モード (Presentation Mode)

- 日付: 2026-07-08
- 対象: feature/presentation-mode(HEAD d614a0a)
- 検証環境: 隔離インスタンス(FE http://localhost:5174 → BE :8766、一時 data_dir。本番 :8765 非接触)
- 検証者: evaluator エージェント(Playwright、実録音・実 Whisper・実 pdf.js 描画)、確定版レポート: orchestrator
- 仕様: `docs/specs/2026-07-06-presentation-mode-design.md` §9-10

## 総合判定: PASS(初回 9/10 → FAIL 1 件を修正 d614a0a → 再検証 PASS)

## 初回検証(10 項目)

| # | 項目 | 判定 | 証拠 |
|---|---|---|---|
| 1 | 発表を開始ボタン: PDF 表示 / markdown 非表示 / 変換不能 PPTX は disabled+ツールチップ | PASS | AC1-source-list-buttons.png |
| 2 | 発表開始: スライド1(Slide 1 視認)+ 1/5 バー + 右字幕領域 + 左録音コントロール(発表を終了)+ チャット非表示 | PASS | AC2-presentation-start-page1.png |
| 3 | ページ操作 3 系統(▶/ArrowRight/ホイール)+ ホイール連打 3 回で 1 ページのみ(150ms スロットリング) | PASS | AC3-*.png(4枚) |
| 4 | ページ番号クリック → 数値入力 → Enter でジャンプ | PASS | AC4-page-input-jump-to-2.png |
| 5 | 発表中リロード → 発表ビューへ自動復帰、ページ・経過時間とも継続 | PASS | AC5-reload-recovery.png |
| 6 | 終了フロー(Modal 確認/キャンセル継続/ソース化/親子表示) | 初回 FAIL → **修正後 PASS** | AC6-*.png + recheck-d614a0a-*.png |
| 7 | スライド側 SourceViewer「このページでの発言」 | DEFERRED(無音制約)/UI 非破壊は確認 | AC7-*.png |
| 8 | 手動リンク設定 → インデント → 解除 → フラット復帰 | PASS | AC8-*.png(3枚) |
| 9 | 操作ヒントの常時表示なし(N / M のみ) | PASS | AC2〜AC4 で確認 |
| 10 | コンソールエラー 0 件 | PASS | console_messages 全走査 |

## Item 6 の FAIL と修正(d614a0a)

- **症状**: ソース化完了直後、リロードなしではソース一覧に実タイトル(「eval-deck.pdf 発表 2026-07-08」)と親子インデント・「リンクを解除」が反映されない(バックエンド API は完了時点で正しい値を返却)
- **根本原因**: `events.svelte.ts` の SSE ハンドラは source_status イベントのフィールドを upsert するが、ペイロードに title は含まれず、links は setParent/removeParent 経路でしか再取得されていなかった
- **修正**: `currentNotebookStore.refreshSources()`(世代ガード+coalesce)を追加し、SSE 終端イベント(ready/error)で sources+links を再取得。notebook 切替時の stale 応答も無効化
- **再検証(新規発表録音 1 本通し、リロードなし)**: R1 発表→終了 / R2 ソース化完了 / R3 タイトル・16px 子インデント(DOM 実測)・リンク解除ボタン / R4 コンソール 0 件 — **PASS 4/4**(recheck-d614a0a-01〜03.png)

## DEFERRED(ユーザー受入で確認)

- **実発話でのページ紐付け精度**(発言 → chunks.page が表示中ページに正しく割当)— 無音環境では検証不能。ロジックは単体・統合テスト済み(境界 5 ケース+パイプライン統合)
- 発表録音チャンク引用からの「該当スライドを表示」の実データ確認(無音録音はチャンク 0 件のため画面上未通過。コードパスは FE テスト済み)

## 特記事項

- 録音タイトルの既定は親の title を使用(この環境では title=null のため origin ファイル名「eval-deck.pdf」が使われた — テンプレート構造は仕様どおり)
- 同日に複数回発表すると同一タイトルになる(ID は別、リンクも各々正しい)— 仕様どおりだが将来 UX 改善余地
- ADR ドラフト 3 件との逸脱なし(evaluator 確認済み)
- 前回機能(チャット音声入力)由来の既知事象(+layout ハイドレーション)は今回未観測

## 証拠ファイル

本ディレクトリ(`.eval/presentation-mode/`)の AC1〜AC8 各 .png + recheck-d614a0a-01〜03.png
