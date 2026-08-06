---
type: adr-draft
title: 検索精度の判定に judge LLM を使わない
summary: "golden set に正解チャンク本文を持たせ、文字列類似度で採点する。judge LLM の質がスコアを汚染する経路を構造的に断つ。"
status: proposed
date: 2026-08-07
project: NotebookOllama
area: evaluation
category: evaluation
tags:
  - adr
  - draft
related:
  - "[[2026-08-07-ragas-retrieval-eval-design]]"
---

# ADR-draft: 検索精度の判定に judge LLM を使わない

- **ステータス**: 提案(ドラフト・未採番)
- **カテゴリ**: evaluation
- **日付**: 2026-08-07
- **出典**: Ragas評価基盤設計 `docs/specs/2026-08-07-ragas-retrieval-eval-design.md`

## 文脈

RAG 評価の一般的な手法は LLM-as-a-judge だが、本プロジェクトの実行環境は
11GB VRAM であり、judge に足る精度のローカルモデルが確保できるか不明だった。
Stage 2 の VLM OCR モデル選定では、この VRAM 制約下に実用モデルが無いと判明している。

## 決定

golden set に正解チャンクの本文 (`reference_contexts`) を持たせ、
Ragas の `NonLLMContextRecall` / `NonLLMContextPrecisionWithReference` と
自前の recall@k / MRR で採点する。LLM は golden set の候補生成にのみ使い、
その出力は人手レビューを通す。

## 理由

- judge が弱いとスコア自体が信用できず、誤った設計判断を誘発する
- 文字列類似度は再現性が高く、高速で、VRAM を消費しない
- 検索段の評価に限れば「正解チャンクを引けたか」は文字列一致で判定できる
- **実装で判明した裏付け**: 「LLM 生成の ground truth は信用できない」という
  前提は、実測で確認された。Ragas の testset generation を日本語コーパスに
  対して実行したところ、英語の質問、崩れた日本語、原文をそのまま言い換えた
  だけの質問が生成され、しかも3チャンクの処理に約122秒を要した。
  `scripts/eval/build_goldenset.py` の人手レビューゲートがこの経路を
  実用に足るものにしており、レビュー待ちに見合わない場合の逃げ道として
  `--manual` ルートも追加した。これは「スコアリング経路から LLM を
  完全に排除する」という決定を直接裏付ける材料になった

## 影響

- 生成段の指標 (faithfulness / answer relevancy) は当面測れない
- golden set の作成コストが上がる(正解チャンク本文の特定が必要)
- 文字列類似度の閾値 (既定 0.6) が新たなチューニング対象になる。
  閾値ミスで全条件が同スコアに潰れる事故を検知するため、
  自前の recall@k を併置してサニティチェックに使う

## 代替案

- **ローカルLLMをjudgeに**: 完全ローカル完結だが判定精度が未知数
- **Claude API をjudgeに**: 判定精度は最も高いが、技術文書を外部APIへ送ることになる

## 結果

(承認後に記載)

## 教訓

(承認後に記載)
