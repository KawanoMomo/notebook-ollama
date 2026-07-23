# 応答自動継続 (Auto Continuation) 実機視覚検証レポート

## 判定: PASS

- 実行日時: 2026-07-21 10:12 JST / 対象: issue #22, feature/chat-auto-continuation
- dev_server: http://127.0.0.1:8766 (health 200 / auto_continue_max=2 / response_budget_tokens=128 / qwen2.5:0.5b)
- 検証者: evaluator エージェント(Playwright MCP 実機操作)

## AC別 PASS/FAIL 一覧

| AC | 内容 | 結果 | 主要証拠 |
|---|---|---|---|
| AC1 | 自動継続の発動と「続きを生成中… (1/2)(2/2)」表示 | **PASS** | dom-observations.md(2回再現・スピナー付ステータス行 outerHTML)、AC2スクショ(128×3回) |
| AC2 | 警告注記「⚠️…(128×3回)…打ち切られました。」+「▶ 続きを生成」ボタン | **PASS** | AC2-truncated-warning-and-button.png |
| AC3 | 手動継続で同一吹き出しへ追記/本文途中に旧注記なし | **PASS** | AC3-manual-continue-streaming.png / -completed.png、dom-observations.md(注記混入0件) |
| AC4 | リロードで会話履歴+ボタン復元 | **PASS** | AC4-reload-restored.png、GET messages=200 |
| AC5 | 設定「生成」に auto_continue_max(min0/max5)入力+ヒント、0保存 | **PASS** | AC5-settings-auto-continue-max.png、API で auto_continue_max=0 確認後2に復元 |

- console.error: **0件** / network 失敗: **0件**(POST messages=200・POST continue=200 x2・GET messages=200・settings往復=200)
- ADR準拠: draft-2026-07-20-assistant-prefill-continuation=**準拠**、draft-2026-07-20-truncated-persistence-update-in-place=**準拠**、横断ADR 001-011=観測対象外。観測範囲での逸脱**0件**

## 各AC観測事実(要点)

**AC1**: 長出力質問送信後 `done_reason=="length"` 検知で自動継続が発動。実DOMに「続きを生成中… (1/2)」→「(2/2)」を描画(独立2回で再現: t=12.6/13.7s と t=5.6/6.6s)。ステータス行要素は `<div class="caret">` + スピナー `<svg class="spinner">` + テキスト構成で仕様§5どおり。生成が高速(表示約1秒)で離散スクショは取り逃したため、PASS基準が認めるDOM snapshot(outerHTML+時刻付きテキスト)で確証。

**AC2**: 自動継続2回が尽きても打ち切りのため、本文末尾に区切り線→「⚠️ 応答が出力トークン上限(128×3回)に達したため打ち切られました。」→直下に「▶ 続きを生成」ボタン。注記の「128×3回」は予算128×(1+auto_continue_max=2)で仕様§4.2一致。スクショ目視確認済み。

**AC3(レビュー修正点)**: 「▶ 続きを生成」押下で /continue(200)が走り、同じ吹き出しに第7章・第8章が追記ストリーム。ストリーミング中、本文の途中に旧警告注記(⚠️/打ち切られました)は挟まらず、第6→7→8章が連続。MutationObserver 136ティック監視で「本文途中に注記+後続本文」検出は0件(唯一のt=1ms検出はフェード中クラッシュレポートダイアログ本文の誤検知と特定)。継続完了後は自然停止しボタン消滅(仕様§5一致)。

**AC4**: truncated状態でページ再読込後、会話履歴(第4-6章)・警告注記・「▶ 続きを生成」ボタンが全復元。messages.truncated 永続化からの復元が機能。

**AC5**: 設定→「生成・検索」に auto_continue_max(自動継続回数) number入力(min0/max5/step1/初期2)+ヒント文表示。0に変更し「生成設定を保存」で保存 → API で generation.auto_continue_max=0 を確認(検証後 PUT で 2 へ復元、テストハーネス原状回復)。

## 実施上の注記(機能判定に影響なし)

Playwright MCP のブラウザ(profile: mcp-chrome-85eaea1)がセッション中に複数回クラッシュ("Target page closed"→"Browser is already in use")。都度、当該プロファイルの孤児chromeプロセスのみ終了+lockfile/SingletonLock除去で復旧し、DB永続化状態から再開。サーバープロセスには一切不干渉。これは検証手段側の不安定さで、被検証機能の欠陥ではない(console 0・network失敗0が裏付け)。

## 証拠バンドル

- `dom-observations.md`(AC1/AC3のMutationObserver観測ログ) / `console.log`(0件) / `network.txt` / `auto-continuation-source.txt`
- `screenshots/AC2-truncated-warning-and-button.png`
- `screenshots/AC3-manual-continue-streaming.png` / `screenshots/AC3-manual-continue-completed.png`
- `screenshots/AC4-reload-restored.png`
- `screenshots/AC5-settings-auto-continue-max.png`
- `screenshots/AC1-00-before-send.png` / `screenshots/AC1-attempt-status.png`
