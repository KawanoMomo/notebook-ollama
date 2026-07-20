# 実機検証レポート: チャット音声入力(PTT + ハンズフリー)

- 日付: 2026-07-07
- 対象: feature/chat-voice-input(HEAD 62f1076)
- 検証環境: 隔離インスタンス(FE http://localhost:5174 → BE :8766、一時 data_dir。本番 :8765 非接触)
- 検証者: evaluator エージェント(Playwright)、裁定: orchestrator(メインセッション)
- 仕様: `docs/specs/2026-07-05-chat-voice-input-design.md` §8 検証ゲート

## 総合判定: PASS(機能検証 8/8 PASS、無関係な既存欠陥 1 件を別課題化)

evaluator の機械的判定は「項目 9(コンソールエラー 0 件)抵触により FAIL」。
以下の証拠により項目 9 のエラーは本ブランチ起因ではないと裁定し、機能ゲートは PASS とする:

1. エラーは `+layout.svelte` の root ハイドレーション失敗(`TypeError: Cannot read
   properties of undefined (reading 'call')`)で、スタックは Svelte 内部のみ。
   音声入力コード(ChatInput / voiceInput / pttKey / VoiceInputSection)に非到達
2. `git diff master...HEAD` に `+layout.svelte` / `OptInDialog` / crash-report 系の
   変更は一切含まれない(変更は音声入力関連+設定ページナビのみ)
3. 非決定的(セッション中 1 回のみ観測、その後 fresh navigation 3 回で再現 0/3)

→ **別課題**: 「+layout.svelte の非決定的ハイドレーション失敗(OptInDialog の
SSR/CSR 不一致疑い、dev モードで観測)」として追跡する。証拠:
`console-error-hydration.log` / `console-full-session.log`

## チェックリスト別判定

| # | 内容 | 判定 | 証拠 |
|---|---|---|---|
| 1 | 設定画面「音声入力」項目+モード3値ラジオ+PTTキー割当(Space) | PASS | AC1-settings-voice-input-section.png |
| 2 | 常時有効へ変更→保存→Toast→リロード→保持→PTT復帰 | PASS | AC2-mode-handsfree-saved.png / AC2-mode-handsfree-after-reload.png / AC2-save-toast-confirmed.png / AC2-toast-dom-evidence.txt |
| 3 | モード=無効でマイクボタン非表示 | PASS | AC3-mode-off-no-mic-button.png |
| 4 | モード=PTTでマイクボタン表示(送信ボタン横) | PASS | AC4-mode-ptt-mic-button-visible.png |
| 5 | Space 単押し→空白1個・録音状態にならず | PASS | AC5-space-tap-inserts-space-no-recording.png |
| 6 | Space 長押し→録音状態(赤パルス/aria-pressed/経過秒)→解放→変換 | PASS | AC6-space-hold-recording-active.png / AC6-space-release-idle-after-transcribe.png |
| 7 | ハンズフリー: クリックでオン(パルス)→再クリックで待機 | PASS | AC7-handsfree-on-pulse.png / AC7-handsfree-off-idle.png |
| 8 | IME 変換ガード(isComposing 合成イベント、参考情報) | PASS(参考) | AC8-ime-composing-guard-no-recording.png |
| 9 | コンソールエラー 0 件 | 裁定PASS(既存欠陥を別課題化) | console-error-hydration.log |

## 特記事項

- **項目 6 は権限拒否パスではなく許可パスの実疎通を確認できた**: Playwright 環境で
  マイク権限が許可され(fake device)、`POST /api/stt/transcribe` が 200 OK で完走。
  fake device は無音相当のため `text=""` → 空認識パス(仕様 §7)どおり textarea 無変更。
  録音→WAV エンコード→API→UI 復帰のパイプライン全体が実配線で動作
- 項目 6 のホールド再現は `document.dispatchEvent(KeyboardEvent)` による
  keydown→400ms→keyup(pttKey.ts は isTrusted 非依存のため有効な手段)
- ADR 準拠: 横断 ADR(001〜011)・プロジェクト ADR とも該当なし(確認済み)

## DEFERRED(ユーザー受入で確認)

- **マイク実発話での認識精度**(発話→期待テキストがカーソル位置に挿入されること)。
  パイプライン疎通は確認済みだが、実音声の認識品質は Playwright では検証不能

## 証拠ファイル

本ディレクトリ(`.eval/chat-voice-input/`)配下の AC1〜AC8 の .png、
console-*.log、network-full-session.json を参照。

## 追補: 最終レビュー修正(acbc255)後の焦点再検証 — PASS 5/5

最終ブランチレビューで検出された Important 2 件の修正後、focused 再検証を実施:

| # | 検証内容 | 判定 | 証拠 |
|---|---|---|---|
| R1 | ボタンフォーカス中の Space が奪われない(defaultPrevented=false、ボタンが実際に activation) | PASS | recheck-acbc255-R1-button-space-activation.png |
| R2 | textarea で Space 単押し→空白挿入・録音なし(回帰) | PASS | recheck-acbc255-R2-space-tap-textarea-no-recording.png |
| R3 | Space 長押し→録音中(赤パルス・aria-pressed・経過秒)→解放で復帰(色トークン化後の見た目含む) | PASS | recheck-acbc255-R3-space-hold-recording-red.png / -R3-space-release-idle.png |
| R4 | getUserMedia 呼び出しカウント: タップ 3 回で 0、長押し 1 回で 1(マイク誤起動修正の実証) | PASS | recheck-acbc255-R4-hold-gumcalls-1.png |
| R5 | コンソール Errors=0, Warnings=0 | PASS | (console_messages 出力) |

検証前に設定が既定(プッシュトゥトーク/Space)であることを確認済み
(recheck-acbc255-00-settings-default-confirmed.png)。
