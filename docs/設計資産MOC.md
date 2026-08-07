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

> [!tip] コードから逆引きするなら
> 「このコードはどの設計書に規定されているか」は [[実装マップ]] を引く(Grep の代替)。

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
> - [[2026-08-07-citation-evidence-ui-design|出典表示の刷新 — 根拠スパン/原本ページ/選択範囲翻訳]] ✏️

> [!abstract] 取込・検索 (ingestion / retrieval)
> - [[2026-07-20-pdf-table-figure-sidecar-design|PDF表・図サイドカー抽出 (Stage 1)]] ✅
> - [[2026-07-20-vlm-figure-ocr-design|VLM図説明・スキャンPDF OCR (Stage 2)]] ✅
> - [[2026-07-20-visual-embedding-index-design|視覚埋め込み第2インデックス (Stage 3)]] ✅
> - [[2026-07-29-pixelrag-tile-index-design|PixelRAG式タイル索引と検索戦略の選択 (Stage 4)]] ✅

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

## 🧭 ADR（採番済み）

台帳は [[README|docs/adr/README.md]]、カテゴリ定義は [[categories]]。
未採番のドラフトは `docs/adr/drafts/` に置く（**現在0件**）。採番・正式登録は承認後に `/adr` で行います。

> [!note] 発表モード / 音声入力 / ベータ基盤
> - [[001-source-links-generic-parent-child|ADR-001 ソース間結合は汎用親子リンク基盤(source_links)]] — `data-model`
> - [[002-recording-timeline-markers|ADR-002 ページ遷移の記録は録音タイムラインマーカー機構]] — `architecture`
> - [[003-pptx-render-powerpoint-com|ADR-003 PPTX見た目再現は PowerPoint COM で取込時PDF化]] — `external-dep`
> - [[004-chat-voice-input-stateless-stt|ADR-004 チャット音声入力はステートレスSTT + ブラウザ側VAD構成]] — `architecture`
> - [[005-beta-feature-flag-registry|ADR-005 機能提供はコード内フラグレジストリ+設定オプトインのベータ機構]] — `release`

> [!note] 表・図 RAG（Stage 1〜2）
> - [[006-chunk-asset-sidecar|ADR-006 表・図はチャンク紐付きサイドカーアセット方式]] — `data-model`
> - [[007-table-dual-representation|ADR-007 表は本文Markdown+サイドカーHTMLの二重表現]] — `data-model`
> - [[008-figure-desc-standalone-chunk|ADR-008 VLM図説明は独立チャンク方式]] — `data-model`
> - [[009-vlm-ocr-ollama-only|ADR-009 VLM/OCRはOllama一本+エンジン抽象化]] — `external-dep`

> [!note] 視覚検索（Stage 3〜4）
> - [[010-visual-index-qdrant-rrf|ADR-010 視覚インデックスはQdrant別コレクション+RRF融合]] — `retrieval`
> - [[011-visual-embedding-ondemand-transformers|ADR-011 視覚埋め込みはOllama外(transformers)でオンデマンド実行]] — `external-dep` ⚠️ CUDA判断は017で覆された
> - [[014-visual-index-unit-collections|ADR-014 視覚索引の単位はコレクション分離(payloadフィルタでなく)]] — `data-model`
> - [[015-partial-success-per-unit|ADR-015 視覚索引構築の部分成功は単位ごとの独立性を意味する]] — `error-handling`
> - [[016-pixel-native-explicit-failure|ADR-016 pixel_nativeは根拠画像なしで黙って劣化させず明示エラー]] — `error-handling`
> - [[017-torch-cuda-wheel-index|ADR-017 visual extraのtorchはCUDAホイールインデックスに切替]] — `external-dep`

> [!note] 応答の自動継続
> - [[012-assistant-prefill-continuation|ADR-012 打ち切り継続は assistant prefill(末尾assistantメッセージ再送)]] — `architecture`
> - [[013-truncated-persistence-update-in-place|ADR-013 truncatedはmessagesカラム永続化+手動継続は最終assistantメッセージ追記更新]] — `data-model`

> [!note] iGPU/NPU 対応（Phase 1.5）
> - [[018-openai-compat-second-contract|ADR-018 LLM/Embeddingの第二共通契約としてOpenAI互換APIを採用]] — `architecture`
> - [[019-llm-backend-vulkan-promotion|ADR-019 iGPUのLLM経路をOllama Vulkanに一本化しIPEX-LLM/DirectML系idを廃止]] — `external-dep`

## 📋 ECN（変更通知）

git履歴から抽出した「何を・なぜ・どう変えたか」。台帳は [[README|docs/ecn/README.md]]、
姉妹プロジェクトへの照合結果は [[横展開分析_姉妹プロジェクト]]。

> [!note] 表・図 RAG シリーズ
> - [[ECN-001_表・図サイドカー抽出とベータ機能フラグ基盤|ECN-001 表・図サイドカー抽出とベータ機能フラグ基盤]] (Stage 1 / PR #24)
> - [[ECN-002_VLM図説明とスキャンPDF-OCR|ECN-002 VLM図説明・スキャンPDF OCR]] (Stage 2 / PR #25)
> - [[ECN-003_視覚埋め込み第2インデックスとRRF融合|ECN-003 視覚埋め込み第2インデックスとRRF融合]] (Stage 3 / PR #26)
> - [[ECN-004_PixelRAG式タイル索引と検索戦略の選択|ECN-004 PixelRAG式タイル索引と検索戦略の選択]] (Stage 4 / PR #27)

> [!note] その他の機能
> - [[ECN-007_チャット音声入力|ECN-007 チャット音声入力(PTT+ハンズフリー)]] (PR #18)
> - [[ECN-008_発表モード|ECN-008 発表モード(スライド+録音+ページ紐付け)]] (PR #19)
> - [[ECN-009_応答の自動継続|ECN-009 応答の自動継続(assistant prefill)]] (PR #23)

> [!tip] 横展開価値が高いもの
> - [[ECN-005_torch-CUDA化とrecording-extraとの共存不可|ECN-005 torchのCUDA化とrecording extraとの共存不可]] — **HIGH**（GPU依存を持つ全プロジェクト）
> - [[ECN-006_視覚索引の複合主キー移行|ECN-006 SQLiteテーブル再作成によるスキーマ移行]] — SQLiteを使う全プロジェクト

## 🏷️ ステータス凡例

| アイコン | status | 意味 |
|---|---|---|
| ✅ | `approved` | 承認済み / 実装済み |
| 👀 | `review` | レビュー・合意待ち |
| ✏️ | `draft` | ドラフト |
| 📋 | `planned` | プラン待ち |
| ⏸️ | `deferred` | 保留 |
| 💡 | `proposed` | ADR提案（未採番） |
