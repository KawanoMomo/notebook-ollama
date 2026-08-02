---
type: reference
title: ECN 一覧 (NotebookOllama)
summary: "git履歴から抽出した変更通知(ECN)の台帳。何を・なぜ・どう変えたか・影響範囲を1件1ファイルで記録する。"
status: approved
date: 2026-08-02
project: NotebookOllama
area: platform
tags:
  - reference
  - ecn
---

# Engineering Change Notice (ECN) — NotebookOllama

まとまった変更を「何を・なぜ・どう変えたか・影響範囲」の形で構造化して残す。
**コードを読めば分かる「何を」より、「なぜ」と「不採用にした案」に価値がある。**

抽出は `/ecn-from-git` で行う。

## 一覧

| ECN | 種別 | タイトル | 対象 | 横断価値 |
|-----|------|---------|------|---------|
| [001](ECN-001_表・図サイドカー抽出とベータ機能フラグ基盤.md) | 機能追加 | 表・図サイドカー抽出とベータ機能フラグ基盤 (Stage 1) | PR #24 | LOW |
| [002](ECN-002_VLM図説明とスキャンPDF-OCR.md) | 機能追加 + 不具合修正 | VLM図説明・スキャンPDF OCR・生成時画像投入 (Stage 2) | PR #25 | MEDIUM |
| [003](ECN-003_視覚埋め込み第2インデックスとRRF融合.md) | 機能追加 + 不具合修正 | 視覚埋め込み第2インデックスとRRF融合 (Stage 3) | PR #26 | MEDIUM |
| [004](ECN-004_PixelRAG式タイル索引と検索戦略の選択.md) | 機能追加 | PixelRAG式タイル索引と検索戦略の選択 (Stage 4) | PR #27 | LOW |
| [005](ECN-005_torch-CUDA化とrecording-extraとの共存不可.md) | 改善 | torch の CUDA ホイール化と recording extra との共存不可 | PR #27 内 | **HIGH** |
| [006](ECN-006_視覚索引の複合主キー移行.md) | 改善 | SQLite テーブル再作成によるスキーマ移行 (複合主キー化) | PR #27 内 | MEDIUM |
| [007](ECN-007_チャット音声入力.md) | 機能追加 | チャット音声入力 (プッシュトゥトーク + ハンズフリー) | PR #18 | MEDIUM |
| [008](ECN-008_発表モード.md) | 機能追加 | 発表モード (スライド表示 + 録音 + ページ紐付け) | PR #19 | MEDIUM |
| [009](ECN-009_応答の自動継続.md) | 機能追加 | 応答の自動継続 (assistant prefill) | PR #23 | MEDIUM |

## 横展開の価値が高いもの

姉妹プロジェクトへの影響分析は各プロジェクトの `docs/ecn-analysis/` に置く。

1. **[ECN-005](ECN-005_torch-CUDA化とrecording-extraとの共存不可.md)** —
   CUDA メジャー版の混載が同一プロセスで破綻する話。GPU 依存を持つ
   あらゆるプロジェクトに当てはまる。「`torch.cuda.is_available()` が True でも
   GPU で動いているとは限らない」という診断の落とし穴を含む
2. **[ECN-003](ECN-003_視覚埋め込み第2インデックスとRRF融合.md)** —
   ローカルで重い計算を回すツールにおける負荷ノブの必要性
   (BSOD 誘発 / E-core 飽和によるブラウザ競合)。**言語・フレームワークを問わない**
3. **[ECN-006](ECN-006_視覚索引の複合主キー移行.md)** —
   SQLite のテーブル再作成移行の型。autocommit 接続下での原子性確保
4. **[ECN-002](ECN-002_VLM図説明とスキャンPDF-OCR.md)** —
   「LLM の失敗は例外ではなくもっともらしい出力で返る」。LLM を部品として使う
   すべてのプロジェクトに当てはまる

## 未抽出の変更

以下はマージ済みだが ECN 化していない。必要になった時点で `/ecn-from-git` で抽出する。

| PR | 内容 | マージ日 |
|---|---|---|
| #20 / #21 | Obsidian ナレッジ層 (vault化 + frontmatter + MOC/Base/Canvas) | 2026-07-20 |
| #29 | Stage 4 効果測定・ADR採番17件・ECN抽出6件・ナレッジ層の救出 | 2026-08-02 |
| — | iGPU/NPU Phase 1.5 (ADR-018/019、master 直接) | 2026-08-02 |
