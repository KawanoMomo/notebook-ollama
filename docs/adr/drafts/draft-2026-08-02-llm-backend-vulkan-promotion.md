---
type: adr-draft
title: iGPU の LLM 経路を Ollama Vulkan に一本化し IPEX-LLM/DirectML 系 id を廃止する
summary: "ollama-vulkan を Intel/AMD iGPU の auto 選択先に昇格、ipex-llm-ollama(セキュリティ問題)と ollama-directml(実在しない)を削除、amd-whispercpp-dml を vulkan に改名する判断。"
aliases:
  - ollama-vulkan 昇格
status: proposed
date: 2026-08-02
project: NotebookOllama
area: accel
category: アーキテクチャ/バックエンド選定
tags:
  - adr
  - draft
related:
  - "[[2026-06-28-igpu-npu-acceleration-design]]"
  - "[[draft-2026-08-02-openai-compat-second-contract]]"
---

# iGPU の LLM 経路を Ollama Vulkan に一本化し IPEX-LLM/DirectML 系 id を廃止する

## ステータス

Draft(未採番。採番・正式登録はユーザー承認後)

## コンテキスト(2026-08-02 時点の外部事実)

- Ollama は Vulkan バックエンドを公式リリースし、v0.13 以降デフォルト有効。
  Intel iGPU / AMD iGPU(780M/890M 等)の双方をカバーする。
- Ollama への SYCL バックエンド PR (#11160) は未マージクローズ(断念確定)。
- intel/ipex-llm はアーカイブ+ README に "known security issues" 明記。
- Ollama に DirectML バックエンドは存在せず、`ollama-directml` は当初設計の誤り。
- whisper.cpp の GPU バックエンドは CUDA/Vulkan/CoreML/OpenVINO であり DirectML は無い。
  DirectML 自体も maintenance mode(新機能は Windows ML へ)。

## 決定

1. `BACKEND_IDS["LLM"]` を `{ollama-cuda, ollama-vulkan, openai-compat}` とする。
   Intel iGPU / AMD Ryzen AI ホストの auto 選択先は `ollama-vulkan`。
   builder は `ollama-cuda` と共通(Vulkan は Ollama サーバー側の機能。URL 差替不要)。
2. `ipex-llm-ollama` と `ollama-directml` を削除し、import 時 sentinel
   (`_DROPPED_LLM_IDS`)で再導入をガードする。
3. STT の Phase 2 予約 id `amd-whispercpp-dml` を `amd-whispercpp-vulkan` に改名する
   (実装は引き続き Phase 2、実機確保待ち)。

## 検討した代替案

- **IPEX-LLM Portable Zip の継続採用**: 配布物は入手可能だが、約1年半更新なし+
  セキュリティ問題明記のため新規採用不可(当初設計 R1 リスクの顕在化)。
- **llama.cpp SYCL 直運用**: Arc で Vulkan 比約2倍速の報告はあるが、Ollama 本体には
  入らないため別サーバー運用になる。必要なら openai-compat 経由で接続可能
  ([[draft-2026-08-02-openai-compat-second-contract]] がその受け皿)。

## 影響

- 既存 NVIDIA ユーザー(auto → ollama-cuda)への影響なし。
- Phase 2 の Intel/AMD インストールスクリプトから IPEX-LLM Portable Zip 展開が消え、
  「公式 Ollama を入れるだけ」に簡素化される。
- 弱い iGPU では Vulkan が CPU より遅い報告があるため、Smoke Test の性能ゲート
  (spec R5)は必須のまま。
