---
type: adr
title: 打ち切り継続は assistant prefill(末尾 assistant メッセージ再送)で行う
summary: "num_predict 上限による打ち切りの継続を、元 messages + 途中応答全文を assistant ロールで再送する assistant prefill 方式で行う設計判断。"
aliases:
  - assistant prefill
status: approved
date: 2026-07-21
adr: 012
project: NotebookOllama
area: chat
category: architecture
tags:
  - adr
related:
  - "[[2026-07-20-auto-continuation-design]]"
---

# ADR-012: 打ち切り継続は assistant prefill(末尾 assistant メッセージ再送)で行う

- **ステータス**: 承認
- **カテゴリ**: architecture
- **日付**: 2026-07-21
- **対象プロジェクト**: NotebookOllama
- **関連ADR**: なし(応答自動継続設計 `docs/specs/2026-07-20-auto-continuation-design.md` §3 より起票)

## コンテキスト

チャット応答が `response_budget_tokens`(Ollama の `num_predict`)上限で打ち切られる
(issue #22)。思考モデル(qwen3 等)は thinking トークンも予算を消費するため、見かけの
回答が短くても上限に到達しやすい。打ち切り後、続きをどう生成するかが論点。

## 検討した選択肢

### A) 「続けて」プロンプト(継続指示を user ロールで追加)

- 概要: `messages` に `{"role": "user", "content": "続きを生成してください"}` を追加して
  再リクエストする
- メリット: 実装は最も単純。任意の会話 API でそのまま動く
- デメリット: モデルが「はい、続きです:」等の前置きを挿んだり、直前の文を言い直したりする
  リスクがある。継ぎ目の品質がモデル依存で不安定

### B) 予算増で丸ごと再生成

- 概要: `num_predict` を増やして最初から生成し直す
- メリット: 継ぎ目品質の問題が原理的に起きない
- デメリット: 生成済みトークンを全て捨てる。思考モデルは thinking フェーズも丸ごと
  再実行になり、コスト・レイテンシが大きい。`num_predict` を際限なく増やすと
  `num_ctx` 超過のリスクも増す

### C) assistant prefill(採用)

- 概要: `messages` 末尾に「元の messages + これまでの応答全文」を **assistant ロール**で
  追加して再リクエストする。Ollama(および OpenAI 互換 API 全般)は末尾メッセージが
  assistant のとき、そのメッセージの続きとして生成する(prefill 動作)
- メリット: 追加プロンプト不要で継ぎ目が自然(前置き・言い直しが起きない)。
  生成済みトークンを保持したまま単純文字列連結で全文を復元できる。実装も単純
- デメリット: 毎ラウンド「元の messages + 全文」を送るため入力トークンが線形に増える。
  `num_ctx` を超えると Ollama 側で古い入力(system prompt や history)が押し出される
  リスクがある

## 決定

C(assistant prefill)を採用する。継ぎ目品質と実装単純性で B・A に優位するため。

`num_ctx` 押し出しリスクへの対策として、無制限の継続は提供しない。継続は
`auto_continue_max`(既定2、範囲0〜5、設定画面で変更可)回で打ち切り、尽きた場合は
チャットでのみ手動継続ボタンをユーザー承認付きで提供する
(`docs/adr/drafts/draft-2026-07-20-truncated-persistence-update-in-place.md` 参照)。
MCP `ask` は自動分のみで手動継続は提供しない(機械呼び出しに人間承認は不成立)。

実装は `core/generation/stream.py::GenerationService.run` と `core/mcp/tools/ask.py::ask_tool`
の双方に同じループ構造で入れる(コード重複はあるが、チャットと MCP で呼び出し文脈
(SSE イベント有無、DB永続化有無)が異なるため、無理な共通化はせず素朴な重複を許容した)。

## 結果

(2026-07-23 実装・マージ済み、PR #23 / issue #22 — 詳細は [[ECN-009_応答の自動継続|ECN-009]])

- 決定どおり、`done_reason == "length"` を検出して末尾 assistant メッセージを
  積んで再送する prefill 方式で実装。回数は `auto_continue_max`(既定2、0-5)
- **想定外だったのは「注記が prefill に混入する」問題**(`fix(web/store)`)。
  打ち切り注記(「上限に達したため打ち切られました」)を本文に含めたまま
  prefill すると、モデルが**注記の続き**を書き始める。継続前に注記を除去する
  経路が必要だった。**表示用の装飾と生成入力の分離**という論点は ADR 起票時に
  想定していなかった
- MCP (`ask`) にも同じループを適用。ただし継続ラウンドの AppError は
  graceful degradation とし、途中本文を捨てず注記を付けて返す
  (`fix(mcp/ask)`)。初回ラウンドの失敗だけは本物のエラーとして投げる
- 実機検証は全 AC PASS


## 教訓

- **prefill 方式では「モデルに見せる本文」と「利用者に見せる本文」を分ける。**
  UI 都合で足した注記・装飾をそのまま prefill すると、モデルはその続きを書く。
  この分離は設計時に明示しておくべきだった
- **リトライ/継続の失敗は初回の失敗と区別する。** 初回は投げてよいが、
  継続の失敗ですでに得た本文を捨てるのは損失。「途中まで + 事情の注記」が
  正しい落とし所
- 「続きを書いて」と user メッセージで頼む案を採らなかったのは正解だった。
  prefill なら前置きの繰り返しも文体の変化も起きない

