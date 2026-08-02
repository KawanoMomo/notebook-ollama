---
type: reference
title: ADR カテゴリ定義 (NotebookOllama)
summary: "NotebookOllama のプロジェクトローカル ADR で使うカテゴリ略称の定義。新規 ADR 作成時はここから選ぶ。"
status: approved
date: 2026-08-02
project: NotebookOllama
area: platform
tags:
  - reference
  - adr
---

# ADR カテゴリ定義 — NotebookOllama

新規 ADR 作成時はこのリストから該当カテゴリを選択する。
該当するものがなければカテゴリを追加し、このファイルを更新する。

横断 ADR (`E:\00_Git\docs\adr\categories.md`) は GUI エディタ系プロジェクトを
対象にした語彙 (interaction / dsl / rendering / semantics) が中心のため、
RAG バックエンドである本プロジェクトでは以下を別途定義する。
`architecture` のみ横断側と同義。

| カテゴリ | 略称 | 対象となる意思決定 |
|---------|------|-------------------|
| アーキテクチャ | `architecture` | モジュール分割・レイヤ構造・結合度・拡張ポイントの設計 |
| データモデル | `data-model` | 永続化スキーマ・データ表現・チャンク/アセットの持ち方・マイグレーション方針 |
| 検索・取得 | `retrieval` | インデックス構成・検索戦略・ランキング/融合方式・チャンク選択 |
| 取込パイプライン | `ingestion` | ソース取込の段階構成・抽出方式・前処理の責務分割 |
| 外部依存 | `external-dep` | Ollama / transformers / COM 等の外部依存の採否・パッケージング・リソース管理 |
| エラー処理 | `error-handling` | 失敗時の縮退方針・部分成功の意味論・ユーザーへの通知粒度 |
| リリース管理 | `release` | 機能の出し方・フラグ運用・ベータ提供の枠組み |

## 使い分けの注意

- **`data-model` と `ingestion`**: 「何をどう保存するか」は `data-model`、
  「どの段階で誰が作るか」は `ingestion`。表・図サイドカー (ADR-006) は
  保存形式の判断なので `data-model`
- **`retrieval` と `data-model`**: インデックスの**構成**(コレクション分離など)は
  データの持ち方なので `data-model`、**検索の仕方**(融合方式・戦略)は `retrieval`
- **`external-dep`**: 「Ollama 一本」原則からの逸脱を伴う判断はここに集める。
  この原則の例外が増えていないかを一覧で監視できるようにするため
