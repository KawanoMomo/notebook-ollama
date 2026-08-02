---
type: reference
title: ADR 一覧 (NotebookOllama)
summary: "NotebookOllama のプロジェクトローカル ADR 台帳。採番規則・ステータス語彙・全 ADR の一覧。"
status: approved
date: 2026-08-02
project: NotebookOllama
area: platform
tags:
  - reference
  - adr
---

# Architecture Decision Records — NotebookOllama

本プロジェクト固有のアーキテクチャレベルの意思決定を記録する。
複数プロジェクトに横断する判断は `E:\00_Git\docs\adr\` に置く (採番系列は別)。

## 命名規則

`NNN-タイトル(英語kebab-case).md`

例: `010-visual-index-qdrant-rrf.md`

採番は本プロジェクト内で 001 から連番。横断 ADR とは独立した系列のため、
参照時は「ADR-010 (NotebookOllama)」のように所属を明示する。

## ステータス

frontmatter は英語語彙 (`check_design_index.py` が検査)、本文表記は日本語。

| frontmatter | 本文 | 意味 |
|---|---|---|
| `proposed` | 提案 | 検討中 (`drafts/` 配下の未採番ドラフト) |
| `approved` | 承認 | 採用済み・適用中 |
| `deferred` | 保留 | 判断を先送り |
| — | 却下 | 不採用 (採番せずドラフトのまま残す) |
| — | 廃止 | 以前は承認されていたが後続 ADR で置き換えられた |

> [!important] 採番のルール
> ドラフト (`drafts/`) の採番と正式登録は**必ず承認を得てから**行う。
> ドラフト止まりが正常な状態であり、未採番であること自体は問題ではない。

## 関連

- [categories.md](categories.md) — カテゴリ定義 (新規追加時はここを参照・更新)
- [[設計資産MOC]] — 設計書と ADR の索引ノート
- [[実装マップ]] — コード → 設計書の逆引き

## 一覧

| ADR | カテゴリ | タイトル | ステータス | 日付 | 起票元 |
|-----|---------|---------|-----------|------|--------|
| [001](001-source-links-generic-parent-child.md) | data-model | ソース間ナレッジ結合は汎用親子リンク基盤(source_links)で実現する | 承認 | 2026-07-06 | 発表モード |
| [002](002-recording-timeline-markers.md) | architecture | ページ遷移の記録は録音セッションの汎用タイムラインマーカー機構で行う | 承認 | 2026-07-06 | 発表モード |
| [003](003-pptx-render-powerpoint-com.md) | external-dep | PPTXの見た目再現はPowerPoint COMによる取込時PDF化 | 承認 | 2026-07-06 | 発表モード |
| [004](004-chat-voice-input-stateless-stt.md) | architecture | チャット音声入力はステートレス STT + ブラウザ側 VAD 構成 | 承認 | 2026-07-07 | 音声入力 |
| [005](005-beta-feature-flag-registry.md) | release | 機能提供はコード内フラグレジストリ+設定オプトインのベータ機構とする | 承認 | 2026-07-20 | ベータ基盤 |
| [006](006-chunk-asset-sidecar.md) | data-model | 表・図はチャンク紐付きサイドカーアセット方式で保存する | 承認 | 2026-07-20 | 表・図 Stage 1 |
| [007](007-table-dual-representation.md) | data-model | 表は本文Markdown+サイドカーHTMLの二重表現とする | 承認 | 2026-07-20 | 表・図 Stage 1 |
| [008](008-figure-desc-standalone-chunk.md) | data-model | VLM図説明は独立チャンク方式で検索に乗せる | 承認 | 2026-07-20 | 表・図 Stage 2 |
| [009](009-vlm-ocr-ollama-only.md) | external-dep | VLM/OCRはOllama一本+エンジン抽象化とする | 承認 | 2026-07-20 | 表・図 Stage 2 |
| [010](010-visual-index-qdrant-rrf.md) | retrieval | 視覚インデックスはQdrant別コレクション+RRF融合とする | 承認 | 2026-07-20 | 表・図 Stage 3 |
| [011](011-visual-embedding-ondemand-transformers.md) | external-dep | 視覚埋め込みはOllama外(transformers)でオンデマンド実行する | 承認 | 2026-07-20 | 表・図 Stage 3 |
| [012](012-assistant-prefill-continuation.md) | architecture | 打ち切り継続は assistant prefill(末尾 assistant メッセージ再送)で行う | 承認 | 2026-07-21 | 自動継続 |
| [013](013-truncated-persistence-update-in-place.md) | data-model | truncated は messages カラムで永続化し手動継続は最終 assistant メッセージの追記更新で行う | 承認 | 2026-07-21 | 自動継続 |
| [014](014-visual-index-unit-collections.md) | data-model | 視覚索引の単位はコレクション分離(payloadフィルタでなく)とする | 承認 | 2026-07-30 | 表・図 Stage 4 |
| [015](015-partial-success-per-unit.md) | error-handling | 視覚索引構築の部分成功は単位ごとの独立性を意味する | 承認 | 2026-07-30 | 表・図 Stage 4 |
| [016](016-pixel-native-explicit-failure.md) | error-handling | pixel_native は根拠画像なしで黙って劣化させず明示エラーにする | 承認 | 2026-07-30 | 表・図 Stage 4 |
| [017](017-torch-cuda-wheel-index.md) | external-dep | visual extraのtorchはCUDAホイールインデックスに切替、CPUはフォールバックとして残す | 承認 | 2026-07-30 | 表・図 Stage 4 |

## 「結果」「教訓」が未記入の ADR

ADR の価値は決定そのものより **「決定どおりになったか」** にある。実装後に結果を
書き戻さないと、次に同じ判断をするときの材料が残らない。以下は実装・マージ済み
にもかかわらず該当節が `(実装後に記載)` のままのもの。

| ADR | 起票元 | 状態 |
|---|---|---|
| [001](001-source-links-generic-parent-child.md) [002](002-recording-timeline-markers.md) [003](003-pptx-render-powerpoint-com.md) | 発表モード (PR #19) | **未記入** — PR #19 の ECN 化と合わせて埋める |
| [012](012-assistant-prefill-continuation.md) [013](013-truncated-persistence-update-in-place.md) | 自動継続 (PR #23) | **未記入** — PR #23 の ECN 化と合わせて埋める |
| [005](005-beta-feature-flag-registry.md) [006](006-chunk-asset-sidecar.md) [007](007-table-dual-representation.md) | 表・図 Stage 1 (PR #24) | ✅ 記入済 ([[ECN-001_表・図サイドカー抽出とベータ機能フラグ基盤\|ECN-001]] より) |
| [008](008-figure-desc-standalone-chunk.md) [009](009-vlm-ocr-ollama-only.md) | 表・図 Stage 2 (PR #25) | ✅ 記入済 ([[ECN-002_VLM図説明とスキャンPDF-OCR\|ECN-002]] より) |

> [!warning] 採番時の反省
> 2026-08-02 の一括採番では、決定内容だけを見て `approved` を付け、結果節が
> 空である点を確認しなかった。**次回からは採番の受入条件に「結果節が埋まって
> いること」を含める。**
>
> 結果節を埋める材料は git 履歴にある。ECN 抽出 (`/ecn-from-git`) を先に回すと
> 検証済みの事実が手に入り、そこから書き戻せる。**ECN → ADR の順が効率的。**

## 判断が覆った経緯

後続の測定や実装で前提が変わった ADR は**破棄せず残し**、覆した ADR への
前方参照を追記する。「なぜその時そう判断したか」自体が資産のため。

| 元の ADR | 覆した ADR | 何が変わったか |
|---|---|---|
| [011](011-visual-embedding-ondemand-transformers.md) | [017](017-torch-cuda-wheel-index.md) | 「CUDA は Ollama 常駐下で CPU より遅い」(cu126 実測) が cu130 で再現せず、約147倍高速と判明 |
