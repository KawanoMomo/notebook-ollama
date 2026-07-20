---
type: adr-draft
title: 視覚インデックスはQdrant別コレクション+RRF融合とする
summary: "ページ視覚埋め込みをFAISSでなくQdrant別コレクションに置き、テキスト検索とRRFで自動融合する設計判断。"
aliases:
  - 視覚インデックス基盤
status: proposed
date: 2026-07-20
project: NotebookOllama
area: retrieval
category: アーキテクチャ/検索
tags:
  - adr
  - draft
related:
  - "[[2026-07-20-visual-embedding-index-design]]"
---

# ADR-draft: 視覚インデックスはQdrant別コレクション+RRF融合とする

- **ステータス**: 提案(ドラフト・未採番)
- **カテゴリ**: アーキテクチャ/検索
- **日付**: 2026-07-20
- **出典**: 視覚埋め込みインデックス設計 `docs/specs/2026-07-20-visual-embedding-index-design.md`

## コンテキスト

ページ全体の視覚埋め込み(1ページ=1ベクトル)の置き場所と、既存テキスト検索との統合方式の選定。PixelRAG参照実装はFAISSを使う。

## 検討した選択肢

### A) Qdrant別コレクション(pages_visual)+RRF自動融合

- メリット: 既存ベクトルストア基盤・運用の再利用。RRFでUI不変のシームレス統合。未構築ノートブックは自動スキップで挙動不変
- デメリット: RRF定数等のチューニング要素が増える

### B) FAISS別持ち(PixelRAG準拠)

- メリット: 参照実装に近い
- デメリット: ベクトルストアが二系統になり運用が割れる

### C) 視覚検索を別モード(UIトグル)

- メリット: コストが明示的
- デメリット: ユーザーが毎回判断する手間、OFFのまま忘れられがち

## 決定

A を採用する。RRF(k=60)でテキストtop-kと視覚top-kを統合し、ページヒットは該当ページの先頭2チャンク+ページ画像に展開して既存budgeter→生成に流す。同一ページの重複は視覚側を吸収する。

## 結果

(実装後に記載)

## 教訓

(実装後に記載)
