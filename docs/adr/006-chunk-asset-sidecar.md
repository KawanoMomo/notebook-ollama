---
type: adr
title: 表・図はチャンク紐付きサイドカーアセット方式で保存する
summary: "chunk_assetsテーブル+ファイル保存でチャンクに表・図を紐付け、ベクトルには乗せず、再取込=削除再構築とする設計判断。"
aliases:
  - チャンクアセットサイドカー
status: approved
date: 2026-07-20
adr: 006
project: NotebookOllama
area: ingestion
category: data-model
tags:
  - adr
related:
  - "[[2026-07-20-pdf-table-figure-sidecar-design]]"
---

# ADR-006: 表・図はチャンク紐付きサイドカーアセット方式で保存する

- **ステータス**: 承認
- **カテゴリ**: data-model
- **日付**: 2026-07-20
- **出典**: 表・図サイドカー設計 `docs/specs/2026-07-20-pdf-table-figure-sidecar-design.md`

## コンテキスト

PDFの表・図はプレーンテキスト抽出で欠損する。表・図の実体(HTML/画像)をどこに保存し、検索・生成とどう結び付けるかの選定が必要。

## 検討した選択肢

### A) chunk_assets テーブル + ファイル保存(サイドカー)

- メリット: チャンク構造・ベクトルストアを変えずに追加できる。ソース単位の一括削除が容易。スライドPDF併産(`<id>.slides.pdf`)と同型で運用が揃う
- デメリット: チャンクとの紐付け整合を自前管理する必要がある

### B) チャンク本文にすべて埋め込む(HTML直挿入)

- メリット: 紐付け管理不要
- デメリット: 埋め込みトークンを浪費し検索品質が下がる。画像は表現不可

### C) ベクトルストア(Qdrant)のpayloadに保存

- メリット: 検索ヒットと同時に取得できる
- デメリット: Qdrantが実体ストアになり肥大化。SQLite側とのJOIN運用(引用・プレビュー)と乖離

## 決定

A を採用する。`chunk_assets`(id/source_id/chunk_id/kind/page/bbox/html/md_snippet/image_path)+`data/assets/<source_id>/` にファイル保存。ベクトルには乗せない。再取込・ソース削除時は行とディレクトリを一括削除して再構築する(冪等)。

## 結果

(実装後に記載)

## 教訓

(実装後に記載)
