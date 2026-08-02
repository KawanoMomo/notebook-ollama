---
title: 設計資産 MOC
summary: "設計資産(specs/ADR)の索引ノート。LLM/エージェントの参照起点。"
aliases:
  - 設計資産MOC
  - 設計資産
type: moc
project: NotebookOllama
tags:
  - moc
  - index
---

# 🗂️ 設計資産 MOC — Notebook Ollama

このノートは `docs/specs`(設計書)と `docs/adr`(ADR)の入口です。横断ビューは [[設計資産.base|設計資産 Base]]、関係図は [[設計資産.canvas|設計資産 Canvas]] を参照してください。

> [!info] 使い方
> - **一覧・絞り込み** → 下の埋め込み Base（領域別/ステータス別/ADR台帳/カード）
> - **構成と機能の全体像** → [[設計資産.canvas]]（システム構成 → coreモジュール → 設計書 → ADR を1枚で俯瞰）
> - 各docの `frontmatter` に `status` / `area` / `related` を付与済み。`status_inferred: true` は本文に明記が無く内容から推定した値です。

## 横断ビュー

![[設計資産.base]]

## 📐 設計書（機能領域別）

> [!abstract] 基盤
> - [[notebook-ollama-design|Notebook Ollama 設計仕様書(基盤)]] ✅
> - [[2026-07-20-beta-feature-flags-design|汎用ベータ機能フレームワーク (Feature Flags)]] ✅

> [!abstract] 録音 (recording)
> - [[2026-06-17-recording-source-design|録音ソース機能]] ✅
> - [[2026-06-19-recording-naming-design|録音の自動命名・ソース名編集]] ✅
> - [[2026-06-22-recording-mute-and-rename-design|録音チャンネル個別ミュート + 話者名一括リネーム]] 👀

> [!abstract] RAG運用UX (rag-ux)
> - [[2026-06-19-rag-ux-improvements-design|RAG運用UX改善(群1)]] ✅
> - [[2026-06-25-source-guide-design|Source Guide(ソースガイド)]] ✅
> - [[2026-07-02-job-status-bar-optimistic-ui-design|ジョブ状態可視化 + Optimistic UI]] ✅

> [!abstract] 取込・検索 (ingestion / retrieval)
> - [[2026-07-20-pdf-table-figure-sidecar-design|PDF表・図サイドカー抽出 (Stage 1)]] ✅
> - [[2026-07-20-vlm-figure-ocr-design|VLM図説明・スキャンPDF OCR (Stage 2)]] ✅
> - [[2026-07-20-visual-embedding-index-design|視覚埋め込み第2インデックス (Stage 3)]] ✅

> [!abstract] 要約 (summary)
> - [[2026-06-26-meeting-adr-templates|議事録テンプレ + ADR 抽出機能]] ✅
> - [[2026-06-26-summary-prompt-tune|要約プロンプト改善 — 選定根拠]] ✅

> [!abstract] モデル / 推論基盤
> - [[2026-06-19-model-selection-design|Ollama モデル選択(LLM/埋め込み)切替]] ✅
> - [[2026-06-28-igpu-npu-acceleration-design|Intel iGPU/NPU・AMD Ryzen AI 対応]] 👀

> [!abstract] その他機能
> - [[2026-06-26-prompt-injection-design|Prompt Injection(プロンプト挿入ツールバー)]] ✅
> - [[2026-06-28-crash-report-feedback-hub-design|クラッシュレポート & フィードバックハブ]] ✅
> - [[browser-notifications-design|Browser Notifications]] ✅
> - [[2026-07-02-developer-mode-design|開発者モード]] ✏️
> - [[2026-07-06-presentation-mode-design|発表モード (Presentation Mode)]] ✅
> - [[2026-07-05-chat-voice-input-design|チャット音声入力]] ✅
> - [[2026-07-20-auto-continuation-design|応答自動継続 (Auto Continuation)]] ✅
> - [[2026-06-21-youtube-source-design|YouTube ソース機能]] ⏸️（保留）

## 🧭 ADR ドラフト（未採番）

採番・正式登録は承認後に `/adr` で行います。

> [!question] 提案中の設計判断
> - [[draft-2026-07-06-source-links-generic-parent-child|ソース間結合は汎用親子リンク基盤(source_links)]] — データモデル（発表モード起票）
> - [[draft-2026-07-06-recording-timeline-markers|ページ遷移の記録は録音タイムラインマーカー機構]] — アーキテクチャ/結合度（発表モード起票）
> - [[draft-2026-07-06-pptx-render-powerpoint-com|PPTX見た目再現は PowerPoint COM で取込時PDF化]] — 外部依存/取込パイプライン（発表モード起票）
> - [[chat-voice-input-stateless-stt|チャット音声入力はステートレスSTT + ブラウザ側VAD構成]] — アーキテクチャ/結合度（音声入力起票）
> - [[draft-2026-07-20-chunk-asset-sidecar|表・図はチャンク紐付きサイドカーアセット方式]] — データモデル/取込（表・図Stage 1起票）
> - [[draft-2026-07-20-table-dual-representation|表は本文Markdown+サイドカーHTMLの二重表現]] — データ表現（表・図Stage 1起票）
> - [[draft-2026-07-20-figure-desc-standalone-chunk|VLM図説明は独立チャンク方式]] — データモデル（表・図Stage 2起票）
> - [[draft-2026-07-20-vlm-ocr-ollama-only|VLM/OCRはOllama一本+エンジン抽象化]] — アーキテクチャ/外部依存（表・図Stage 2起票）
> - [[draft-2026-07-20-visual-index-qdrant-rrf|視覚インデックスはQdrant別コレクション+RRF融合]] — アーキテクチャ/検索（表・図Stage 3起票）
> - [[draft-2026-07-20-visual-embedding-ondemand-transformers|視覚埋め込みはOllama外(transformers)でオンデマンド実行]] — 外部依存/リソース管理（表・図Stage 3起票）
> - [[draft-2026-07-20-beta-feature-flag-registry|機能提供はコード内フラグレジストリ+設定オプトインのベータ機構]] — アーキテクチャ/リリース管理（ベータ基盤起票）
> - [[draft-2026-07-20-assistant-prefill-continuation|打ち切り継続は assistant prefill(末尾assistantメッセージ再送)]] — アーキテクチャ/結合度（自動継続起票）
> - [[draft-2026-07-20-truncated-persistence-update-in-place|truncatedはmessagesカラム永続化+手動継続は最終assistantメッセージ追記更新]] — データモデル（自動継続起票）
> - [[draft-2026-08-02-openai-compat-second-contract|LLM/Embeddingの第二共通契約としてOpenAI互換APIを採用]] — アーキテクチャ/外部連携（iGPU/NPU Phase 1.5起票）
> - [[draft-2026-08-02-llm-backend-vulkan-promotion|iGPUのLLM経路をOllama Vulkanに一本化しIPEX-LLM/DirectML系idを廃止]] — アーキテクチャ/バックエンド選定（iGPU/NPU Phase 1.5起票）

## 🏷️ ステータス凡例

| アイコン | status | 意味 |
|---|---|---|
| ✅ | `approved` | 承認済み / 実装済み |
| 👀 | `review` | レビュー・合意待ち |
| ✏️ | `draft` | ドラフト |
| 📋 | `planned` | プラン待ち |
| ⏸️ | `deferred` | 保留 |
| 💡 | `proposed` | ADR提案（未採番） |
