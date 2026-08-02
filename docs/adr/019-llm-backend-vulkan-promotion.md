---
type: adr
title: iGPU の LLM 経路を Ollama Vulkan に一本化し IPEX-LLM/DirectML 系 id を廃止する
summary: "ollama-vulkanをIntel/AMD iGPUのauto選択先に昇格、ipex-llm-ollama(セキュリティ問題)とollama-directml(実在しない)を削除、amd-whispercpp-dmlをvulkanに改名する判断。"
aliases:
  - ollama-vulkan 昇格
status: approved
date: 2026-08-02
adr: 019
project: NotebookOllama
area: accel
category: external-dep
tags:
  - adr
related:
  - "[[2026-06-28-igpu-npu-acceleration-design]]"
  - "[[018-openai-compat-second-contract]]"
---

# ADR-019: iGPU の LLM 経路を Ollama Vulkan に一本化し IPEX-LLM/DirectML 系 id を廃止する

- **ステータス**: 承認
- **カテゴリ**: external-dep
- **日付**: 2026-08-02
- **出典**: Intel iGPU/NPU・AMD Ryzen AI 対応 `docs/specs/2026-06-28-igpu-npu-acceleration-design.md` addendum K1/K2/N
- **関連ADR**: ADR-018 (NotebookOllama)

## コンテキスト(2026-08-02 時点の外部事実)

- Ollama は Vulkan バックエンドを公式リリースし、v0.13 以降デフォルト有効。
  Intel iGPU / AMD iGPU(780M/890M 等)の双方をカバーする(当初設計時は「将来」扱い)
- Ollama への SYCL バックエンド PR (#11160) は未マージクローズ(断念確定)
- intel/ipex-llm はアーカイブに加え README に "known security issues" が明記された
  (当初設計 R1 リスクの顕在化)
- Ollama に DirectML バックエンドは存在せず、Sprint 2 で導入した `ollama-directml` は
  設計誤り。whisper.cpp にも DirectML バックエンドは無く(CUDA/Vulkan/CoreML/OpenVINO)、
  DirectML 自体が maintenance mode(新機能は Windows ML へ移行)

## 検討した選択肢

### A) 公式 Ollama の Vulkan バックエンドに一本化

- 概要: `BACKEND_IDS["LLM"]` を `{ollama-cuda, ollama-vulkan, openai-compat}` とし、
  Intel iGPU / AMD Ryzen AI ホストの auto 選択先を `ollama-vulkan` にする。
  builder は `ollama-cuda` と共通(Vulkan は Ollama サーバー側の機能。URL 差替不要)
- メリット: ユーザーは公式 Ollama を入れるだけ。専用 ZIP 展開・子プロセス管理
  (`RuntimeSupervisor`)が丸ごと不要になる。ROCm が Windows APU 非対応の AMD でも動く
- デメリット: 弱い iGPU では Vulkan が CPU より遅い報告あり(Smoke Test 性能ゲート
  R5 で吸収)。SYCL 比で Intel iGPU の性能は劣る報告あり

### B) IPEX-LLM Portable Zip の継続採用(当初設計)

- 概要: spec §4.3 当初案の `ipex-llm-ollama`
- メリット: Intel iGPU での実績値(Arc 140V で qwen3:8b ~17-18 tok/s)
- デメリット: 上流アーカイブ+セキュリティ問題明記+約1年半更新なし。採用不能

### C) llama.cpp SYCL ビルドの直運用

- 概要: Intel Arc で Vulkan 比約2倍速の報告がある SYCL を別サーバーとして運用
- メリット: Intel iGPU の性能最大化
- デメリット: Ollama 本体には入らないため別サーバー運用になる。必要なら
  ADR-018 の `openai-compat` 経由で接続できる(専用経路は不要)

## 決定

A を採用する。`ipex-llm-ollama` と `ollama-directml` は削除し、`backend_ids.py` の
import 時 sentinel(`_DROPPED_LLM_IDS`)で再導入を構造的にガードする。STT の
Phase 2 予約 id `amd-whispercpp-dml` は実態に合わせ `amd-whispercpp-vulkan` に改名する
(実装は引き続き Phase 2、実機確保待ち)。SYCL 級の性能が必要なケースは ADR-018 の
openai-compat が受け皿となる。

## 結果

Phase 1.5 として実装済み。Planner 表駆動テストで Intel iGPU / AMD Ryzen AI の全 HW
プロファイルが `ollama-vulkan` に到達することを確認(BE 全 1604 件 PASS)。既存
NVIDIA ユーザー(auto → ollama-cuda)への回帰は CUDA 数値ゲート 3 件 PASS と実機起動
検証で確認。dropped-id sentinel は import 時に発火することをテストで担保した。
Intel/AMD 実機での Vulkan 実測は開発機に対象 HW が無いため未実施(Phase 2 の
受入条件 AC-INTEL/AC-AMD に持ち越し)。

## 教訓

- 外部ランタイムの「将来対応予定」を前提にした backend id は**存在しない機能の名前**
  になりうる(`ollama-directml`)。id 追加時は対象バックエンドの実在を一次情報で確認する
- アーカイブ済み OSS への依存は、配布物が残っていても**セキュリティ表記が付いた時点で
  採用不能**と判断する。spec のリスク表(R1)に「顕在化時の代替」を書いておいたことで
  差し替え判断が速かった
