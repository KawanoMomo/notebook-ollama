---
type: adr
title: 視覚インデックスはQdrant別コレクション+RRF融合とする
summary: "ページ視覚埋め込みをFAISSでなくQdrant別コレクションに置き、テキスト検索とRRFで自動融合する設計判断。"
aliases:
  - 視覚インデックス基盤
status: approved
date: 2026-07-20
adr: 010
project: NotebookOllama
area: retrieval
category: retrieval
tags:
  - adr
related:
  - "[[2026-07-20-visual-embedding-index-design]]"
---

# ADR-010: 視覚インデックスはQdrant別コレクション+RRF融合とする

- **ステータス**: 承認
- **カテゴリ**: retrieval
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

(2026-07-26 実装・実機検証済み、PR: feature/visual-embedding)

- 決定どおり実装: `pages_visual` コレクション(既存Qdrantクライアント共有 —
  ローカルモードの1パス1クライアント制約のため必須)、RRF k=60、同一ページは
  視覚側を吸収、ページヒットは先頭2チャンク+チャンク無しページは合成チャンク
  (`vp:<source_id>:<page>`)に展開
- evaluator実機で全8シナリオPASS: 視覚のみヒット(画像だけのページ)の検索到達・
  「p.N(視覚検索)」引用・vision対応チャットモデルへのページ画像late-binding投入・
  ベータOFF/トグルOFFのフォールバックを確認
- 実装中の発見: `RetrievalService.search()` の「テキストヒット0件で早期return」が
  視覚のみヒットを不達にしていたため撤去(挙動はvisual未配線なら不変)

## 教訓

- RRF融合を入れると「片側0件」の経路が新設計になる。既存検索の早期returnは
  融合前提では成立しない
- Qdrantローカルモードの第2コレクションは必ずクライアント共有で設計すること
  (別クライアントはファイルロックで即死する)
