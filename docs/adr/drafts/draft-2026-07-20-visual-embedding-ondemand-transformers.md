---
type: adr-draft
title: 視覚埋め込みはOllama外(transformers)でオンデマンド実行する
summary: "Ollama非対応の視覚埋め込みをtransformers+extra依存で実行し、オンデマンドロード+アイドルアンロードで11GB VRAMと共存させる設計判断。"
aliases:
  - 視覚埋め込み実行基盤
status: proposed
date: 2026-07-20
project: NotebookOllama
area: retrieval
category: 外部依存/リソース管理
tags:
  - adr
  - draft
related:
  - "[[2026-07-20-visual-embedding-index-design]]"
  - "[[draft-2026-07-20-visual-index-qdrant-rrf]]"
---

# ADR-draft: 視覚埋め込みはOllama外(transformers)でオンデマンド実行する

- **ステータス**: 提案(ドラフト・未採番)
- **カテゴリ**: 外部依存/リソース管理
- **日付**: 2026-07-20
- **出典**: 視覚埋め込みインデックス設計 `docs/specs/2026-07-20-visual-embedding-index-design.md`

## コンテキスト

Ollamaは画像埋め込みモデル(Qwen3-VL-Embedding等)に対応していないため、視覚埋め込みには「Ollama一本」原則の例外が必要。RTX 2080 Ti 11GBでチャットLLMと共存させる制約もある。

## 検討した選択肢

### A) transformers + `--extra visual` + オンデマンドロード/アイドルアンロード

- メリット: 必要な人だけが導入するオプション依存(recording extraと同型)。fp16で4〜5GBをロードし既定5分のアイドルで解放、チャットLLMとVRAM衝突を回避
- デメリット: 「Ollama一本」原則の例外が生まれる。初回クエリにロード時間(数秒)

### B) 常駐ロード

- メリット: クエリ遅延最小
- デメリット: 11GBでチャットLLMと同時常駐は不安定

### C) Ollama対応を待つ/独自サーバ化

- メリット: 原則維持
- デメリット: 実現時期不明で機能が塞がる。独自サーバは過剰

## 決定

A を採用する。例外は視覚埋め込みに限定し、`OcrEngine` 同様の抽象化でOllama側が対応した場合の回帰余地を残す。CUDA不可環境はCPUフォールバック(所要時間目安を表示)。

## 結果

(実装後に記載)

## 教訓

(実装後に記載)
