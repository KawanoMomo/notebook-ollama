---
type: spec
title: VLM図説明・スキャンPDF OCR (Stage 2)
summary: "Ollama VLMで図クロップの説明文を独立チャンク化して検索に乗せ、画像のみPDFをOCR取込可能にする。生成時はVLM選択中のみ図画像をlate-binding投入する。"
aliases:
  - VLM図説明
  - vlm-figure-ocr
status: approved
date: 2026-07-20
project: NotebookOllama
area: ingestion
tags:
  - spec
  - ingestion
  - rag
  - vlm
related:
  - "[[2026-07-20-pdf-table-figure-sidecar-design]]"
  - "[[2026-07-20-visual-embedding-index-design]]"
  - "[[2026-06-19-model-selection-design]]"
  - "[[2026-07-20-beta-feature-flags-design]]"
---

# VLM図説明・スキャンPDF OCR (Stage 2) 設計書

## 1. 背景と目的

Stage 1([[2026-07-20-pdf-table-figure-sidecar-design]])で図はクロップPNG+チャンク紐付けまで保存されるが、内容はテキスト化されず検索にかからない。また画像のみPDF(スキャン文書)は取込自体が失敗する。Stage 2はこの2つを Ollama VLM で解消し、「検索は安価なテキストで広く、高価な視覚読解はヒット分だけ」という late-binding 構成の読解側を完成させる。

## 2. スコープ

### 対象 (in)

- 図クロップに対する VLM 説明文生成 → **独立チャンク化**(埋め込み・検索対象)
- 画像のみPDFのページ全体 OCR 取込(現状の取込失敗を解消)
- 生成時: チャットモデルが vision 対応の場合のみ、ヒットした図チャンクのクロップ画像をコンテキスト投入
- 既存ソースへの手動「図を解析」操作(Stage 1保存済みクロップを処理、再取込不要)
- 引用バッジ/Source Viewer での図クロップ表示(クロップ配信APIを含む)
- Unlimited-OCR の実機検証スパイク(タイムボックス、本体非ブロック)

### 対象外 (out)

- 視覚埋め込みによる検索(Stage 3)
- docx/pptx/xlsx のアセット抽出(横展開ロードマップ)
- OCR専用エンジン(PaddleOCR等)の組み込み(スパイク結果と品質実績を見て将来判断)

## 3. 確定済み判断(ユーザー合意)

| 論点 | 決定 |
|---|---|
| 実行経路 | Ollama一本(既存ゲートウェイ・モデル切替UI活用)。Unlimited-OCRは将来を見越した検証スパイクのみ |
| 説明文の格納 | 図1つ=1独立チャンク(既存チャンク不変、再埋め込み不要、図単位の引用が可能) |
| 処理タイミング | 新規取込はパイプライン組込みで自動(設定でOFF可)、既存ソースは手動「図を解析」 |
| 生成時の図読込 | チャットモデルがVLMのときのみ画像投入。非VLMは説明文のみ(グレースフルデグラデーション) |
| 提供形態 | ベータ(シリーズ共通フラグ `table-figure-rag`、既定OFF、[[2026-07-20-beta-feature-flags-design]]) |

## 提供形態(ベータ) — フラグOFF時の挙動

本機能は `table-figure-rag` フラグ(表・図シリーズ共通)配下のベータ機能として提供する。

- **OFF時**: 取込のdescribe段・スキャンPDFのOCR経路はスキップ(スキャンPDFは従来どおり取込エラー)。「図を解析」・クロップ配信API・図画像投入・視覚モデル(VLM)スロットは非露出(APIは403+有効化ヒント)
- **生成済みの図説明チャンク**: OFF時は検索から除外する(`kind='figure_desc'` をフィルタ)。データ自体は保持し、ONに戻せば再び検索に乗る

## 4. アーキテクチャ

```
[取込時(自動、設定でOFF可)]
PDF ─▶ Stage 1抽出(表・図クロップ) ─▶ チャンク化・埋め込み(既存)
        └─▶ describe段(新設): 図クロップ ─▶ Ollama VLM ─▶ 説明文
              └─▶ 図説明チャンク(text=説明文, page, kind='figure_desc')
                    ─▶ 埋め込み ─▶ Qdrant(既存コレクション)
                    └─▶ chunk_assets.desc_chunk_id に紐付け

[スキャンPDF]
パース時に抽出テキスト空 ─▶ OCR経路: ページ画像レンダリング ─▶ Ollama VLM(OCRプロンプト)
        ─▶ ページテキスト ─▶ 通常のチャンク化・埋め込みへ(既存の取込失敗エラーを置換)

[生成時(late-binding)]
検索ヒットに図説明チャンク ─▶ チャットモデルのvision capability判定(Ollama /api/show)
        ├─ VLM: 説明文+クロップ画像(上限あり)を投入
        └─ 非VLM: 説明文のみ
```

- VLM呼び出しは既存 `core/ollama` ゲートウェイに画像付きリクエストを追加して行う
- OCR/図説明の呼び出しは `OcrEngine` / `FigureDescriber` インターフェースで抽象化し、将来の専用エンジン差し替え(スパイク結果次第)に備える

## 5. データモデル

- `chunks` に `kind TEXT NOT NULL DEFAULT 'text'` を追加し、図説明チャンクは `kind='figure_desc'` で区別する(migrations パターンで追加。既存行はDEFAULTで互換)
- `chunk_assets` に `desc_chunk_id TEXT nullable` を追加(figureアセット→説明チャンクのリンク)。Stage 1 の `chunk_id`(同一ページ本文チャンクへの紐付け)は保持
- 「図を解析」の実行状態はソース単位で管理(未解析図の残数が分かること)

## 6. モデル選択

- モデル選択UIに**視覚モデル(VLM)スロット**を追加(LLM/埋め込みに続く3つ目、既存の選択・検証パターンを踏襲)
- 視覚モデル未選択時: 取込のdescribe段はスキップ(取込は成功)、「図を解析」は未選択ガイドを表示(recording extra 503+ヒントと同型)
- 図説明チャンクは通常のテキスト埋め込みモデルで埋め込むため、**埋め込みモデル切替=再インデックスの既存制約に変更なし**。VLMの切替は再インデックス不要(説明文を作り直したい場合のみ「図を解析」を再実行)

## 7. 生成時の図画像投入

- vision capability は Ollama `/api/show` の capabilities で判定しキャッシュする
- top-k 内の図説明チャンクのうち、投入する画像は**最大2枚**(コンテキスト圧迫防止、QAログ参照)。3枚以上ヒット時は検索スコア上位を優先
- budgeter は説明文テキストのみを数える。画像トークンはOllama側の扱いに依存するため、画像を投入するときは available_tokens から固定マージン(1枚あたり1000トークン)を差し引いて安全側に倒す

## 8. API / UI(evaluatorスクショ検証ゲート対象)

- API: `POST /api/notebooks/{notebook_id}/sources/{source_id}/describe-figures`(202、未解析図のみ処理。ジョブ状態バーに乗せる)
- API: `GET /api/notebooks/{notebook_id}/sources/{source_id}/assets/{asset_id}`(クロップPNG配信、FileResponse。スライドPDF配信と同型)
- UI: ソース行の既存メニューに「図を解析」を追加(縦肥大化なし)。視覚モデル未選択時は無効化+ヒント
- UI: 図説明チャンクの引用バッジ/Source Viewerでクロップ画像をサムネイル表示
- 設定: 「取込時に図を自動解析する」トグル(既定ON)

## 9. エラー処理

- 図1枚のVLM失敗はログ+スキップし、残りの図と取込全体は継続(部分成功)。未解析分は「図を解析」で再実行可能
- スキャンPDFのOCRで全ページ失敗した場合のみ取込エラー(従来の「no extractable text」に相当する新メッセージ+視覚モデル設定への導線)
- クロップ画像欠損時は画像投入・表示をスキップ(Stage 1のフォールバックと同じ)
- VLM応答が空/極端に短い場合はリトライ1回、それでも失敗ならスキップ

## 10. テスト

- **unit**: 説明文→独立チャンク生成(決定的なメタデータ)、capability判定のキャッシュ、画像投入の上限選択、budgeterマージン
- **integration**: fake ollama(vision応答モック)で describe段→図説明チャンク+埋め込み+desc_chunk_id 紐付け、スキャンPDF経路、部分失敗の継続、「図を解析」の未解析分のみ処理
- **UI**: evaluator実機スクショで「図を解析」フロー、引用バッジのクロップ表示、視覚モデル未選択時のガイド

## 11. QAログ(推奨値で先行決定した非クリティカル論点)

| 論点 | 決定(推奨値) | 理由 |
|---|---|---|
| 説明文プロンプト | 日本語で「図種別+要点+読み取れる数値・ラベル」を要求 | 検索語彙と回答素材の両立 |
| 生成時の画像投入上限 | 最大2枚 | 11GB VRAMとコンテキスト圧迫の抑制 |
| OCRレンダリングDPI | 150(Stage 1クロップと同値) | 精度と処理時間のバランス |
| VLM推奨モデル | qwen3-vl系を第一候補としてドキュメントに記載 | 日本語・表図読解の実績 |
| スキャンPDF判定 | 全ページの抽出テキストが空のとき(部分スキャンはStage 2では非対応) | 判定の単純化、混在文書は将来課題 |
| Unlimited-OCRスパイク | タイムボックス半日。RTX 2080 Ti(Turing)でfp16+eager attentionで起動可否のみ検証、結果はレポートとしてdev_logsに記録 | bf16/flash-attn非対応の公算大、本体に組み込まない |

## 12. 起票予定のADRドラフト(spec承認後に作成)

1. **図説明は独立チャンク方式** — 既存チャンク不変・再埋め込み回避・図単位引用(カテゴリ: データモデル)
2. **VLM/OCRはOllama一本+エンジン抽象化** — 専用OCRスタックはインターフェース差し替えで将来判断(カテゴリ: アーキテクチャ/外部依存)

## 13. 参照

- 前段: [[2026-07-20-pdf-table-figure-sidecar-design]](クロップ保存・chunk_assets)
- 後段: [[2026-07-20-visual-embedding-index-design]](視覚検索)
- モデル選択: [[2026-06-19-model-selection-design]](スロット追加のパターン)
- 調査対象: [Unlimited-OCR](https://github.com/baidu/Unlimited-OCR)
