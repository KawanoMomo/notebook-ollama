---
type: adr
title: truncated は messages カラムで永続化し手動継続は最終 assistant メッセージの追記更新で行う
summary: "打ち切りフラグを messages.truncated カラムで永続化し、手動継続では新規メッセージを作らず最終 assistant メッセージへ追記更新する(citations再計算+conversations.updated_at bump)設計判断。"
aliases:
  - truncated永続化
  - 追記更新
status: approved
date: 2026-07-21
adr: 013
project: NotebookOllama
area: chat
category: data-model
tags:
  - adr
related:
  - "[[2026-07-20-auto-continuation-design]]"
---

# ADR-013: truncated は messages カラムで永続化し手動継続は最終 assistant メッセージの追記更新で行う

- **ステータス**: 承認
- **カテゴリ**: data-model
- **日付**: 2026-07-21
- **対象プロジェクト**: NotebookOllama
- **関連ADR**: なし(応答自動継続設計 `docs/specs/2026-07-20-auto-continuation-design.md` §4.3/4.4 より起票)

## コンテキスト

自動継続(`auto_continue_max` 回)が尽きてもまだ `done_reason=="length"` の場合、
チャットUIに「続きを生成」ボタンを出し、ユーザー承認で手動継続する(R3)。この手動継続を
リロード後も可能にする(R4)には、打ち切り状態と、継続結果をどう永続化・反映するかを
決める必要がある。

## 検討した選択肢

### A) 手動継続を新規メッセージとして追加

- 概要: 「続きを生成」を押すたびに新しい assistant メッセージ行を `messages` に INSERT する
- メリット: 実装は追記更新より単純(常に新規行)。既存の `append_message` をそのまま使える
- デメリット: 1つの回答が複数のメッセージ行に分裂し、履歴表示・エクスポート・
  citation番号(`build_citations` は1メッセージ全文基準)の一貫性が崩れる。
  ユーザー体験としても「1つの吹き出しに見せたい」という要件(§5 UI)に反する

### B) truncated 状態をメモリのみで保持(DB非永続化)

- 概要: `truncated` フラグをレスポンス(SSE done イベント)にだけ載せ、DBには保存しない
- メリット: migration不要
- デメリット: リロード後は打ち切り状態が失われ、手動継続ボタンを復元できない(R4違反)

### C) truncated をカラム永続化 + 最終メッセージ追記更新(採用)

- 概要: `messages` テーブルに `truncated INTEGER NOT NULL DEFAULT 0` を追加
  (既存の冪等 migration パターン: `PRAGMA table_info` → `ALTER TABLE ADD COLUMN`)。
  手動継続では新規メッセージを作らず、`messages_repo.update_message_content(id, content,
  citations, truncated)` で最終 assistant メッセージの content・citations・truncated を
  書き換える
- メリット: 1つの回答=1メッセージ行の一貫性を維持。リロード後も `truncated` フラグから
  ボタンを復元できる(R4)。citations は継続後の全文で `build_citations` を再実行して
  置換するため、参照番号のズレが起きない
- デメリット: 追記更新用の repo メソッドが別途必要(単純な INSERT では済まない)

## 決定

C を採用する。1つの回答としての履歴・エクスポートの整合性を最優先する(QAログ §8 参照)。

- 手動継続完了時は最終 assistant メッセージを更新すると同時に `conversations.updated_at`
  を bump する(会話一覧の並び順・「最新更新」表示を継続後の状態に追従させるため)
- 手動継続の prefill は保存済み全文から**警告注記を除去したもの**を使う
  (`strip_truncation_note`)。注記をモデルに見せないことと、FE 側の継続中表示に
  旧注記が残らないことの両方に効く
- 手動継続の retrieval は元質問文 + 現在の source_ids 選択で再実行する(元 source_ids は
  DB非保存のため)。qdrant検索は間に ingest がなければ決定的なので citation 番号は維持される

## 結果

(2026-07-23 実装・マージ済み、PR #23 / issue #22 — 詳細は [[ECN-009_応答の自動継続|ECN-009]])

- 決定どおり `messages.truncated` カラムで永続化し、手動継続は最終 assistant
  メッセージの追記更新(`update_message_content`)で実装。会話の見た目は
  「1つの回答が伸びる」まま
- リロード後も打ち切り状態と「続きを生成」ボタンが復元されることを実機で確認
- **更新系に穴があった**: `update_message_content` が存在しない ID で黙って
  成功し、`updated_at` も更新していなかった(`fix(storage)`)。呼び出し側の
  バグを隠す実装だった
- **手動継続で履歴の重複除去が正しいメッセージを消す不具合**も出た
  (`fix(api)`)。追記更新方式は「同じ ID のメッセージが伸びる」ため、
  ID ベースの dedup と相性の悪い箇所があった


## 教訓

- **状態を1カラム足すだけの機能でも、更新系の穴は出る。** not-found を
  黙って通す更新関数は、呼び出し側のバグを隠して発見を遅らせる。
  影響が無いように見えても not-found は明示的に扱う
- **「1つの回答が伸びる」見た目を選ぶと追記更新が必要になる。** メッセージを
  増やす方が実装は簡単だが、会話ログが継続回数だけ分割されて読みにくい。
  この選択のコストは「既存の ID ベース処理(dedup 等)との相性」に出る
- 永続化する状態を増やしたら、**リロード復帰の経路を必ず実機で確認する**。
  自動テストは状態の保存を検証できても、復帰後の UI までは見ない

