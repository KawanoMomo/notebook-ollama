---
type: adr-draft
title: Ragas はメトリクス計算層に限定して使う
summary: "Ragas のフレームワーク全体には乗らず、non-LLM メトリクスの計算にのみ使う。スイープ制御と実行制御は自前で持ち、Ragas を差し替え可能に保つ。"
status: proposed
date: 2026-08-07
project: NotebookOllama
area: evaluation
category: external-dep
tags:
  - adr
  - draft
related:
  - "[[2026-08-07-ragas-retrieval-eval-design]]"
---

# ADR-draft: Ragas はメトリクス計算層に限定して使う

- **ステータス**: 提案(ドラフト・未採番)
- **カテゴリ**: external-dep
- **日付**: 2026-08-07
- **出典**: Ragas評価基盤設計 `docs/specs/2026-08-07-ragas-retrieval-eval-design.md`

## 文脈

検索精度の定量指標が無く、表・図RAG Stage 4 の効果測定が定性的な結論に留まった。
評価基盤を導入するにあたり、Ragas をどこまで使うかを決める必要があった。

## 決定

Ragas は `core/eval/metrics.py` の内部でのみ import し、non-LLM メトリクスの
計算にのみ使う。設定マトリクスの展開、条件の実行制御、レポート生成は自前で持つ。
`EvaluationDataset` / 統合 `evaluate()` API / LLM ラッパー抽象には依存しない。

## 理由

- 必要なのは設計判断の決着であり、Ragas そのものではない
- Ragas の抽象に全面依存すると、ローカル埋め込みと Ollama のラッパー実装を抱え、
  Ragas のバージョン変更に追従し続けるコストが発生する
- メトリクス層を薄く保てば、Ragas が期待外れだった場合に差し替えられる

## 影響

- `ragas` は `eval` extra に隔離され、本番インストールには含まれない
- Ragas API の変更を吸収する箇所は `core/eval/metrics.py:_ragas_scores` の1箇所のみ
- 将来 faithfulness 等の生成段メトリクスへ拡張する場合、同じ関数に追加する
- **実装で判明した副次効果**: ragas 0.4.3 は import 時に
  `langchain_community.chat_models.vertexai` を無条件 import するが、
  langchain-community はこのモジュールを 0.4.x で削除済みで、ragas 側は
  バージョン固定を宣言していない。実行時に必要な `rapidfuzz` も未宣言だった。
  どちらも `eval` extra 内のピン留め(`langchain-community<0.4`,
  `rapidfuzz>=3.0`)で吸収できた。`langchain*` はこの層を通してしか
  プロジェクトに入らないため、影響範囲が `eval` extra 一つに収まった。
  もし Ragas のフレームワークに全面依存していたら、この上流破損が
  評価基盤全体を止めていた
- `ragas.metrics` は `ragas.metrics.collections` への移行を促す
  DeprecationWarning を出すが、移行先には NonLLM 系のメトリクスが無い。
  現状は非推奨経路が唯一の選択肢であり、`_ragas_scores` の import 部で
  この警告のみを狭く抑制している

## 代替案

- **Ragas フル活用**: 生成段評価への拡張は滑らかだが、結合が強く逃げ道がない
- **Ragas 不使用**: 依存ゼロで最速だが、生成段評価に進む際に作り直しになる

## 結果

(承認後に記載)

## 教訓

(承認後に記載)
