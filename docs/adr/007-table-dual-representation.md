---
type: adr
title: 表は本文Markdown+サイドカーHTMLの二重表現とする
summary: "検索・埋め込みはチャンク本文のMarkdown表、生成・表示は完全HTMLを使い分け、結合セル表のみ生成時にHTML置換する設計判断。"
aliases:
  - 表の二重表現
status: approved
date: 2026-07-20
adr: 007
project: NotebookOllama
area: ingestion
category: data-model
tags:
  - adr
related:
  - "[[2026-07-20-pdf-table-figure-sidecar-design]]"
  - "[[006-chunk-asset-sidecar]]"
---

# ADR-007: 表は本文Markdown+サイドカーHTMLの二重表現とする

- **ステータス**: 承認
- **カテゴリ**: data-model
- **日付**: 2026-07-20
- **出典**: 表・図サイドカー設計 `docs/specs/2026-07-20-pdf-table-figure-sidecar-design.md`

## コンテキスト

表をチャンク・埋め込み・生成・UI表示のどの形式で持つか。Markdownはトークン効率が良いが結合セルを表現できず、HTMLは構造を保持できるが埋め込みには冗長。

## 検討した選択肢

### A) 本文Markdown + サイドカーHTML(二重表現)

- メリット: 埋め込みはトークン効率の良いMarkdown、生成・表示は構造保持のHTMLと役割分担できる
- デメリット: 二重管理。置換照合キー(md_snippet)が必要

### B) HTMLのみ(本文にもHTML)

- メリット: 単一表現
- デメリット: 埋め込みトークン浪費、検索語彙がタグに埋もれる

### C) Markdownのみ

- メリット: 最小
- デメリット: 結合セル・複雑構造が失われ、生成が表を誤読する

## 決定

A を採用する。取込時に表領域の本文テキストを除外してMarkdown表を挿入し、完全HTMLを chunk_assets に保存。生成時は**結合セルを含む表のみ** md_snippet→HTML に置換し、単純表はMarkdownのまま投入してトークンを節約する。

## 結果

(実装後に記載)

## 教訓

(実装後に記載)
