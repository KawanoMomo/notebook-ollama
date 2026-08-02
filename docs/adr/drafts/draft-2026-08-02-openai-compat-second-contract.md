---
type: adr-draft
title: LLM/Embedding の第二共通契約として OpenAI 互換 API を採用する
summary: "Ollama HTTP API に加え OpenAI 互換 API を共通契約とし、OpenAICompatClient を _ClientLike 注入で追加。生成と埋め込みは独立エンドポイント(非対称構成)とする設計判断。"
aliases:
  - openai-compat 第二契約
status: proposed
date: 2026-08-02
project: NotebookOllama
area: accel
category: アーキテクチャ/外部連携
tags:
  - adr
  - draft
related:
  - "[[2026-06-28-igpu-npu-acceleration-design]]"
---

# LLM/Embedding の第二共通契約として OpenAI 互換 API を採用する

## ステータス

Draft(未採番。採番・正式登録はユーザー承認後)

## コンテキスト

iGPU/NPU 対応 spec の 2026-08-02 追従調査で、Ollama 以外のローカル LLM ランタイム
(llama.cpp `llama-server` / OpenVINO Model Server / Lemonade Server / LM Studio /
Foundry Local)がいずれも **OpenAI 互換 HTTP API** を提供していることが確認された。
一方、Intel 経路の本命だった IPEX-LLM はアーカイブ+セキュリティ問題明記で採用不能になった。

## 決定

1. Ollama HTTP API(第一契約)に加え、**OpenAI 互換 API を第二の共通契約**とする。
2. 実装は `OpenAICompatClient`(`core/ollama/openai_compat.py`)。既存
   `_ClientLike` Protocol を満たし、`OllamaGateway` の `_client` 注入だけで透過切替する
   (Gateway・上位層は非変更)。エラーは既存 `AppError` コードへ正規化する。
3. backend id `openai-compat` / `openai-compat-embed` は **auto 選択しない**
   (自動検出では互換サーバーの存在も URL も分からない)。user override 専用。
4. **生成と埋め込みは独立エンドポイント**(`openai_compat_endpoint` /
   `openai_compat_embed_endpoint`)。NPU 経路で embedding まで完走できるランタイムが
   実質存在しないため、「生成=NPU/iGPU、埋め込み=iGPU/CPU」の非対称構成を一級とする。

## 検討した代替案

- **OVGenAIClient(OpenVINO GenAI 直叩き)**: OVMS が OpenAI 互換 API を提供するため
  優先度低下。カスタム adapter の保守コストに見合わない。
- **ランタイム個別クライアント(Lemonade 専用等)**: 各サーバーが OpenAI 互換を話す以上、
  個別実装は不要。互換 API 1 本で全候補に接続できる。

## 影響 / 既知制限(Phase 1.5 時点)

- チャット・RAG(取込/検索の埋め込み)は openai-compat 経路で動作する。
- **モデルメタ層(/api/show・タグ一覧・vision capability・設定 UI のモデル検証)は
  Ollama 前提のまま**。openai-compat 時は num_ctx 既定 8192、vision probe は best-effort
  で False。設定 UI からの compat モデル選択は不可(settings.json 手編集)。
- 録音パイプラインは LLM 補助タスクと埋め込みが同一 dep のため Ollama 前提のまま。
- endpoint 未設定で openai-compat を強制した場合は起動時に remediation 付きで明示停止
  (spec §6.1「LLM は黙って切替えない」)。
