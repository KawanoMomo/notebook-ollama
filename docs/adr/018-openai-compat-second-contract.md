---
type: adr
title: LLM/Embedding の第二共通契約として OpenAI 互換 API を採用する
summary: "Ollama HTTP APIに加えOpenAI互換APIを共通契約とし、OpenAICompatClientを_ClientLike注入で追加。生成と埋め込みは独立エンドポイント(非対称構成)とする設計判断。"
aliases:
  - openai-compat 第二契約
status: approved
date: 2026-08-02
adr: 018
project: NotebookOllama
area: accel
category: architecture
tags:
  - adr
related:
  - "[[2026-06-28-igpu-npu-acceleration-design]]"
  - "[[019-llm-backend-vulkan-promotion]]"
---

# ADR-018: LLM/Embedding の第二共通契約として OpenAI 互換 API を採用する

- **ステータス**: 承認
- **カテゴリ**: architecture
- **日付**: 2026-08-02
- **出典**: Intel iGPU/NPU・AMD Ryzen AI 対応 `docs/specs/2026-06-28-igpu-npu-acceleration-design.md` addendum L/M/Q
- **関連ADR**: ADR-019 (NotebookOllama)

## コンテキスト

iGPU/NPU 対応 spec の 2026-08-02 追従調査で、Ollama 以外の有力ローカル LLM ランタイム
(llama.cpp `llama-server` / OpenVINO Model Server / Lemonade Server / LM Studio /
Foundry Local)がいずれも **OpenAI 互換 HTTP API** を提供していることが確認された。
一方、Intel 経路の本命だった IPEX-LLM はアーカイブ+セキュリティ問題明記で採用不能に
なった(ADR-019)。また同調査で「NPU 経路で embedding まで完走できるランタイムは実質
存在しない」ことも判明し、生成と埋め込みを同一サーバーに縛る暗黙前提が Phase 2 の
制約になることが分かった。

## 検討した選択肢

### A) OpenAI 互換 API を第二の共通契約とし、`OpenAICompatClient` を `_ClientLike` 注入で追加

- 概要: 既存 `OllamaGateway` の `_client` に構造的に差し替え可能なクライアントを1本追加。
  backend id `openai-compat` / `openai-compat-embed` は auto 選択せず user override 専用
- メリット: 互換 API 1 本で全候補ランタイムに接続できる。Gateway・上位層は非変更。
  エラーは既存 `AppError` コードへ正規化され remediation 表示がそのまま機能する
- デメリット: モデルメタ層(/api/show 相当)が無く、num_ctx・vision capability・
  モデル検証は Ollama 前提のまま残る(既知制限)

### B) OVGenAIClient(OpenVINO GenAI 直叩き)を当初設計どおり実装

- 概要: spec §4.3 当初案。OpenVINO GenAI のカスタム adapter
- メリット: Intel NPU に最短距離
- デメリット: OVMS が OpenAI 互換 API を提供するため二重投資。Intel 専用で AMD に効かない

### C) ランタイム個別クライアント(Lemonade 専用等)を都度実装

- 概要: 採用ランタイムごとに専用クライアント
- メリット: 各サーバーの固有機能(hybrid 実行の制御等)まで使える
- デメリット: 各サーバーが OpenAI 互換を話す以上、保守コストに見合わない

## 決定

A を採用する。付随して **生成と埋め込みは独立エンドポイント**とする
(`openai_compat_endpoint` / `openai_compat_embed_endpoint`、後者が空なら前者に
フォールバック)。「生成=NPU/iGPU、埋め込み=iGPU/CPU」の非対称構成を一級とし、
どのベンダーに転んでも設計変更が不要な形にする。endpoint 未設定で openai-compat を
強制した場合は起動時に remediation 付き ValueError で明示停止する
(spec §6.1「LLM は黙って切替えない」)。

## 結果

Phase 1.5 として実装済み(`core/ollama/openai_compat.py` ほか)。BE 全 1604 件 PASS、
CUDA 回帰数値ゲート 3 件 PASS。実機起動検証(隔離 data_dir + port 8791)で
(1) 既定 auto → 従来どおり CUDA プラン(回帰ゼロ)、(2) `runtime_backend=
"openai-compat"` → LLM のみ override され embed は Ollama 側に分離、の両構成の
起動と診断 API 応答を確認した。/code-review で「text_embedder が実配線に未接続で
非対称構成が機能しない」欠陥が見つかり、取込・検索の埋め込みを
`text_embedder.gateway` 経由に配線し直して解消した。

残課題: モデルメタ層(設定 UI のモデル検証・num_ctx・vision 判定)と録音
パイプラインと MCP ask は Ollama 前提のまま(spec addendum Q に既知制限として明記)。
openai-compat の実サーバー(llama-server 等)との疎通実測は未実施。

## 教訓

- 抽象(Protocol)を足しただけでは機能しない。**新しい実装が実際の呼び出し経路に
  配線されているかを必ず消費側から辿って検証する**(text_embedder は DI に存在したが
  誰も呼んでいなかった)
- 設定を「settings.json 手編集のみ」で提供する場合、**設定保存系 API が該当キーを
  保持するか**(固定キー再構築で消えないか)を受入条件に含める
