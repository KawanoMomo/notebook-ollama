---
type: spec
title: 応答自動継続 (Auto Continuation)
summary: "num_predict 上限打ち切り時に assistant prefill で自動継続(最大2回)し、以降はユーザーがボタンで手動継続する機能。チャット+MCP ask 対象。"
aliases:
  - 自動継続
  - Auto Continuation
status: approved
date: 2026-07-20
project: NotebookOllama
area: chat
tags:
  - spec
related:
  - "[[notebook-ollama-design]]"
  - "[[2026-07-05-chat-voice-input-design]]"
---

# 設計仕様: 応答自動継続 (Auto Continuation) — Notebook Ollama

- 日付: 2026-07-20
- ステータス: 承認済み(ブレインストーミング完了)
- 起票元: issue #22「応答が出力トークン上限(4096)に達したため打ち切られました」
- 対象: `core/generation/stream.py` + `core/mcp/tools/ask.py` + `apps/api` chat ルーター + `apps/web` チャットUI + 設定画面

## 1. 目的

チャット応答が `response_budget_tokens`(Ollama の `num_predict`)上限で打ち切られたとき、
現状は警告注記を表示して終わる。本機能は打ち切りを検知したら**自動で続きを生成**して
応答を完成させ、ユーザーが手動で設定値を調整したり質問を分割したりする手間をなくす。

思考モデル(qwen3 等)は thinking トークンも予算を消費するため、見かけの回答が短くても
上限に到達しやすい。これが issue #22 の直接原因である。

## 2. 要件

| # | 要件 |
|---|---|
| R1 | `done_reason == "length"` を検知したら自動で続きを生成する(自動継続) |
| R2 | 自動継続は最大 `auto_continue_max` 回(既定2、範囲0〜5、0=無効)。設定画面「生成」で変更可能 |
| R3 | 自動継続が尽きてもまだ打ち切りの場合、チャットUIに「続きを生成」ボタンを表示し、ユーザー承認で手動継続する |
| R4 | 手動継続はリロード後も可能(truncated 状態を永続化) |
| R5 | MCP `ask` ツールも自動継続の対象(手動継続はなし。尽きたら従来の打ち切り注記) |
| R6 | 継続中であることを UI に表示する(「続きを生成中… (n/max)」) |
| R7 | 継続失敗時は途中までの応答を失わない(graceful degradation) |

## 3. 方式比較と決定

| 案 | 内容 | 評価 |
|---|---|---|
| **X. assistant prefill(採用)** | messages 末尾に途中応答を assistant ロールで付けて再リクエスト。Ollama は末尾が assistant のとき続きから生成する | 追加プロンプト不要、継ぎ目が自然、単純連結で復元可 |
| Y. 「続けて」プロンプト | user ロールで継続指示 | 「はい、続きです:」等の前置き混入・言い直しリスク |
| Z. 予算増で丸ごと再生成 | num_predict を増やして最初から | 生成済みトークンを捨てる。思考モデルは再思考も丸ごと |

判断: X。継ぎ目品質と実装単純性で優位。関連する設計判断は ADR ドラフト起票対象
(実装時に `docs/adr/drafts/` へ)。

## 4. アーキテクチャ

### 4.1 自動継続ループ (`GenerationService.run`)

現在1回の `chat_stream` 呼び出しを最大 `1 + auto_continue_max` 回のループにする。

```
messages = [system] + history + [user_prompt]   # 従来通り
answer_parts = []
for round in 0..auto_continue_max:
    req = messages if round == 0 else messages + [{"role": "assistant", "content": join(answer_parts)}]
    stream = chat_stream(model, req, options={num_ctx, num_predict: response_budget_tokens})
    # token / thinking イベントは従来通り yield(継続分も同じメッセージに流れ続ける)
    if done_reason != "length": break
    if round < auto_continue_max:
        yield GenerationEvent(kind="continuing", data={"round": round + 1, "max": auto_continue_max})
truncated = (最終 round でも done_reason == "length")
```

- 継続の `num_predict` は毎回フル予算(合計上限 = 予算 × (1 + auto_continue_max))
- prefill は毎回「元の messages + これまでの全文」を送る。入力側が伸びるため
  num_ctx 超過時は Ollama 側で古い入力が押し出される。これが継続回数上限の根拠であり、
  無制限継続は提供しない
- `run()` に `auto_continue_max: int` 引数を追加。呼び出し側(chat ルーター / MCP ask)が
  `config.generation.auto_continue_max` を渡す

### 4.2 イベント契約(SSE)

| kind | data | 変更 |
|---|---|---|
| `continuing` | `{round, max}` | **新設**。自動継続の開始通知 |
| `done` | `{answer, citations, model_used, dropped_history, truncated, continued_rounds}` | `continued_rounds`(実施した継続回数)を**追加** |
| `token` / `thinking` / `retrieval` / `error` | 変更なし | |

打ち切り警告注記は自動継続が尽きた場合のみ本文末尾に付け、文言を
「⚠️ 応答が出力トークン上限(4096×3回)に達したため打ち切られました。」の形式に更新する。

継続ラウンド(round>0)自体が Ollama エラーで失敗した場合(R7 graceful degradation)は、
文言を「⚠️ 応答が出力トークン上限(4096×3回)に達したのち、続きの生成に失敗したため
途中までの応答を表示しています。」に分岐する(`core/generation/stream.py` /
`core/mcp/tools/ask.py` 共通)。

### 4.3 手動継続 API(チャットのみ)

`POST /api/notebooks/{notebook_id}/conversations/{conv_id}/continue` (SSE)

リクエストボディは `{"source_ids": [...]}`。元質問時の source_ids は DB に保存されて
いないため、FE が現在のソース選択を送る(既存 send と同じ契約。空は 400)。

1. 対象会話の最後のメッセージが `truncated` な assistant であることを検証
   (違えば 409、notebook/会話なしは 404)
2. 会話中の直近 user 質問と body.source_ids で retrieval を再実行しプロンプトを再構築
   (qdrant 検索は間に ingest がなければ決定的で、citation 番号は維持される)
3. 保存済み assistant 全文から**警告注記を除去したもの**を prefill にして生成
   (注記をモデルに見せない)。モデルは元応答の `message.model` を優先
   (`last.model or nb.default_model or config.ollama.default_model`)。
   ここでも自動継続 `auto_continue_max` 回分が働く
4. 完了時、**最後の assistant メッセージを追記更新**(新規メッセージは作らない)。
   citations は継続後の全文で `build_citations` を再実行して置換。
   `truncated` フラグを最終 done_reason に応じて更新

### 4.4 永続化

- `messages` テーブルに `truncated INTEGER NOT NULL DEFAULT 0` を追加。
  既存の冪等 migration パターン(`PRAGMA table_info` → `ALTER TABLE ADD COLUMN`)に従う
- `messages_repo` に追記更新用の `update_message_content(id, content, citations, truncated)` を追加
- chat ルーターの `append_message` に truncated を渡す

### 4.5 設定

- `GenerationSettings.auto_continue_max: int = 2`(core/config.py)
- スキーマ: `Field(ge=0, le=5)`(apps/api/schemas/settings.py)
- `PUT /api/settings/generation` と settings_store の復元に追加
- 設定画面「生成」に number 入力(min 0 / max 5 / step 1)+ヒント
  「0で自動継続を無効化。打ち切り時の『続きを生成』ボタンは常に使えます」

## 5. UI(チャット画面)

- **継続中表示**: 既存「思考中…」と同じステータス行様式で「続きを生成中… (1/2)」。
  `continuing` イベント受信で表示、次の `token` 受信で消える
- **「続きを生成」ボタン**: truncated な**最後の** assistant メッセージのフッターに配置
  (警告注記の直下、コンパクトに。既存UIを縦に肥大化させない)。
  押下で `/chat/continue` を呼び、同じ吹き出しに追記ストリーム。
  生成中(いずれかの生成進行中)は無効化。継続完了で `truncated` が解除されたら消える
- リロード後は GET 会話履歴のメッセージ `truncated` フラグからボタンを復元

## 6. エラー処理

| ケース | 挙動 |
|---|---|
| 継続リクエスト中の Ollama エラー | それまでの本文+警告注記で正常終了扱い(`truncated: true` のまま done)。手動ボタンで再試行可能 |
| 手動継続: 最後が truncated assistant でない | 409 |
| 手動継続: notebook / 会話なし | 404 |
| 継続で追加トークンなし・即 stop | 正常完了扱い、truncated 解除 |
| num_ctx 超過 | Ollama 側の入力押し出しに委ねる(継続上限で抑制。無制限は提供しない) |

## 7. テスト戦略

- **unit**: 継続ループ(fake gateway: length→length→stop 系列)/ prefill messages 構成 /
  `continuing` イベント / `auto_continue_max=0` / 継続中エラーの degradation /
  警告文言(×N回 形式)
- **integration**: `/chat/continue` 正常・409・404 / `truncated` migration 冪等性 /
  メッセージ追記更新+citations 再計算 / settings PUT の新フィールド往復
- **MCP**: `ask` の自動継続(尽きたら注記)
- **FE (vitest)**: `continuing` 表示 / ボタン表示条件(truncated かつ最終メッセージ、リロード復元)/ 押下で追記
- **evaluator 実機検証**: `response_budget_tokens` を小さくして
  打ち切り→自動継続→ボタン→手動継続の一連をスクリーンショット証拠付きで確認
  (GUI 変更のため visual verification gate 適用)

## 8. QAログ(推奨案で先行決定した非クリティカル論点)

| 論点 | 決定 | 理由 |
|---|---|---|
| 継続時の thinking 抑制 | しない | Ollama/モデル挙動依存を避ける。既存「思考中…」表示が機能し、コストは時間のみ |
| 継続時の num_predict | 毎回フル予算 | 実装単純。合計上限は回数で制御 |
| 警告文言 | 「(予算×N回)に達したため」形式 | 実際の消費上限を正しく伝える |
| 手動継続の retrieval | 同一質問で再実行 | prefill 再構築に必要。決定的なので citation 番号は維持 |
| MCP ask の手動継続 | なし | 機械呼び出しに人間の承認は不成立。自動分のみ |
| DB 追記の方式 | 最終 assistant メッセージを update | 1つの回答として履歴・エクスポートの整合を保つ |
