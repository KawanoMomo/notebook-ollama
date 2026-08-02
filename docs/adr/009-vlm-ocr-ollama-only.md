---
type: adr
title: VLM/OCRはOllama一本+エンジン抽象化とする
summary: "図説明・スキャンOCRを既存Ollamaゲートウェイで実行し、専用OCRスタックはOcrEngine抽象化の差し替え候補に留める設計判断。"
aliases:
  - VLM実行経路
status: approved
date: 2026-07-20
adr: 009
project: NotebookOllama
area: ingestion
category: external-dep
tags:
  - adr
related:
  - "[[2026-07-20-vlm-figure-ocr-design]]"
  - "[[2026-06-19-model-selection-design]]"
---

# ADR-009: VLM/OCRはOllama一本+エンジン抽象化とする

- **ステータス**: 承認
- **カテゴリ**: external-dep
- **日付**: 2026-07-20
- **出典**: VLM図説明・OCR設計 `docs/specs/2026-07-20-vlm-figure-ocr-design.md`

## コンテキスト

図の説明文生成とスキャンPDFのOCRをどの推論基盤で実行するか。開発機はRTX 2080 Ti(Turing, 11GB)で bf16/flash-attn 非対応という制約がある。

## 検討した選択肢

### A) Ollama一本(既存ゲートウェイにVLM呼び出しを追加)

- メリット: 追加依存ゼロ。モデル選択・切替UIの既存パターンをそのまま流用。アプリの「Ollama一本」アーキテクチャを維持
- デメリット: OCR専用モデル比で精度が劣る可能性(特に細かい日本語)

### B) OCR専用エンジン併用(PaddleOCR/RapidOCR等)

- メリット: スキャン文書の精度・CPU実行
- デメリット: Python依存の増加、二系統の運用

### C) Unlimited-OCR等の専用GPUスタック(vLLM/SGLang)

- メリット: 最高精度
- デメリット: Turing非対応の公算大(bf16/flash-attn前提)。検証コスト高

## 決定

A を採用する。呼び出しは `OcrEngine` / `FigureDescriber` インターフェースで抽象化し、B/C への将来差し替えに備える。C は半日タイムボックスの検証スパイクのみ実施し、結果を dev_logs に記録して本体には組み込まない。

## 結果

(実装後に記載)

## 教訓

(実装後に記載)
