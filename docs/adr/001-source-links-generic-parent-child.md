---
type: adr
title: ソース間ナレッジ結合は汎用親子リンク基盤(source_links)で実現する
summary: "ソース間のナレッジ結合を汎用の親子リンク基盤(source_links)で実現する設計判断。"
aliases:
  - source_links
  - 親子リンク基盤
status: approved
date: 2026-07-06
adr: 001
project: NotebookOllama
area: presentation
category: data-model
tags:
  - adr
related:
  - "[[2026-07-06-presentation-mode-design]]"
---

# ADR-001: ソース間ナレッジ結合は汎用親子リンク基盤(source_links)で実現する

- **ステータス**: 承認
- **カテゴリ**: data-model
- **日付**: 2026-07-06
- **対象プロジェクト**: NotebookOllama
- **関連ADR**: なし(発表モード設計 `docs/specs/2026-07-06-presentation-mode-design.md` より起票)

## コンテキスト

発表モードで「発表資料(スライド)と発表録音」を結び付ける必要が生じた。同一ノートブック内の
ソースは従来フラットに並ぶだけで、ソース間の関係性を表現できていなかった。ユーザー要件は
「資料が親、録音やその他資料が子」という汎用の親子登録であり、発表はその第一のユースケース。

## 検討した選択肢

### A) 発表専用の紐付け(録音ソースに deck_source_id カラム追加)

- 概要: 録音ソースへ親資料IDを直接持たせる
- メリット: 実装最小
- デメリット: 発表以外の関係(補足PDF、メモ等)を表現できない。ユーザー要件(汎用リンク)を満たさない

### B) 汎用親子リンクテーブル(source_links)

- 概要: parent/child source_id + relation(presentation/manual) + meta(JSON) の独立テーブル
- メリット: 手動リンクと自動リンクを同一基盤で表現。relation追加で将来拡張可。既存sourcesテーブル無変更
- デメリット: 表示側(ツリー)とAPI(CRUD・循環拒否)の実装が必要

## 決定

B を採用。自己リンク・重複・循環は登録時に拒否。v1のUIはツリー1階層表示(データは多段可)。
手動リンク(relation=manual)はソース単位のみで、ページ紐付けは発表(presentation)だけが持つ。

## 結果

(実装後に記載)

## 教訓

(実装後に記載)
