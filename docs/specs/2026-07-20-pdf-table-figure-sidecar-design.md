---
type: spec
title: PDF表・図サイドカー抽出 (Stage 1)
summary: "PDF取込時に表をMarkdown化してチャンクに反映+完全HTMLをサイドカー保存し、図はクロップPNGでチャンクに紐付ける。RAGの表・図欠損を解消するStage 1設計。"
aliases:
  - 表・図サイドカー
  - table-figure-sidecar
status: review
date: 2026-07-20
project: NotebookOllama
area: ingestion
tags:
  - spec
  - ingestion
  - rag
related:
  - "[[notebook-ollama-design]]"
  - "[[draft-2026-07-06-pptx-render-powerpoint-com]]"
  - "[[2026-06-19-model-selection-design]]"
  - "[[2026-07-02-job-status-bar-optimistic-ui-design]]"
  - "[[2026-07-20-beta-feature-flags-design]]"
---

# PDF表・図サイドカー抽出 (Stage 1) 設計書

## 1. 背景と目的

現状の `PdfParser` は `page.get_text("text")` によるプレーンテキスト抽出のみであり、次の欠損がある。

- **表**: セル構造が破壊され、読み順で潰れた文字列としてチャンクに混入する(検索にも生成にもほぼ寄与しない)
- **図・グラフ**: 完全に脱落する
- **画像のみのPDF**: 取込自体が失敗する(Stage 2 OCRのスコープ、本設計では現状維持)

本設計は取込時に表・図を**サイドカーアセット**として抽出・保存し、表は検索・生成に乗せ、図はStage 2(VLMによるテキスト化)の基盤を作る。基盤設計書の「原本ファイル保持は再パース・将来のOCR対応に備える」という既存判断の延長線上にある。

### 発端と全体構想

PixelRAG(文書を画像のまま検索する視覚RAG)とUnlimited-OCR(画像→構造化テキスト変換)の調査から、ローカルGPU(RTX 2080 Ti 11GB)制約下では「**検索は安価なテキストで広く、高価な視覚読解はヒットチャンクのみ**」というlate-binding構成が最適と判断した。段階計画:

| Stage | 内容 | 状態 |
|---|---|---|
| **Stage 1(本設計)** | PDFの表・図サイドカー抽出、表の検索・生成反映 | 設計中 |
| Stage 2 | VLM/OCRによる図の説明文付与・画像のみPDF対応(Ollama VLM経路が有力) | 構想 |
| Stage 3 | 視覚埋め込みの第2インデックス(PixelRAG式、Qwen3-VL-Embedding等) | 構想(Stage 1/2の効果を見て判断) |
| 横展開 | docxの表落ち修正 → pptx → xlsx(埋め込みグラフ等) | 構想 |

なお docx パーサは `doc.paragraphs` のみ走査しており**表を暗黙に落とすバグ**があることを本設計の調査で確認済み(別課題として横展開ロードマップに登録)。

## 2. スコープ

### 対象 (in)

- PDF取込時の表抽出(PyMuPDF `find_tables()`)→ Markdown化してチャンク本文へ挿入 + 完全HTMLサイドカー保存
- PDF取込時の図抽出(ラスタ画像ブロック)→ クロップPNG保存 + チャンク紐付けまで
- 生成時のヒットチャンクへの表HTML投入(結合セル表のみ置換)
- ソース単位の手動再取込API+UI
- 引用スニペット/Source Viewerでの表HTMLレンダリング表示

### 対象外 (out)

- 図の内容のテキスト化・検索反映(Stage 2)
- 図クロップの表示UI・配信API(Stage 2)
- 画像のみPDF(スキャン文書)の取込対応(Stage 2)
- ベクター線画のクラスタリング検出(誤検出が多くv1対象外)
- 視覚埋め込みインデックス(Stage 3)
- docx/pptx/xlsxのアセット抽出(横展開ロードマップ)

## 3. 確定済み判断(ユーザー合意)

| 論点 | 決定 |
|---|---|
| 対象フォーマット | Stage 1はPDFのみ。最終的にはdocx/pptx/xlsxも(ロードマップ) |
| 図の扱い | クロップ保存+紐付けまで(抽出は取込時にしかできないため、Stage 2で再取込不要になる) |
| 既存ソース | 手動再取込(ソース単位で選んで実行、コストを明示的に制御) |
| UI露出 | 再取込操作+表のHTMLレンダリング表示まで |
| 実現方式 | A案: パーサ拡張型(ParsedDocumentにアセット追加、PdfParser内で抽出) |
| 提供形態 | ベータ(シリーズ共通フラグ `table-figure-rag`、既定OFF、[[2026-07-20-beta-feature-flags-design]]) |

## 提供形態(ベータ) — フラグOFF時の挙動

本機能は `table-figure-rag` フラグ(表・図シリーズ共通)配下のベータ機能として提供する。

- **OFF時**: PdfParserは従来のテキスト抽出のみ(抽出段はスキップ)。再取込API/メニュー、表HTMLレンダリング表示は非露出(APIは403+有効化ヒント)
- **ON期間中のデータ**: OFFに戻しても chunk_assets・クロップPNGは保持され、露出だけが消える(フレームワークのデータ規約)
- **注意**: チャンク本文に挿入済みのMarkdown表はOFF後も本文・埋め込みに残る。完全に従来状態へ戻すには当該ソースの再アップロード(または一時的にONへ戻して再取込)が必要

## 4. アーキテクチャ

```
PDF ─▶ PdfParser
        ├─ 本文テキスト(表領域のブロックは除外して重複防止)
        ├─ 表: find_tables()
        │    ├─ Markdown化 ─▶ セクション本文に挿入(検索・埋め込み対象)
        │    └─ HTML + bbox + md_snippet ─▶ chunk_assets
        └─ 図: ラスタ画像ブロック ─▶ クロップPNG ─▶ chunk_assets
チャンク化(既存chunker) ─▶ 挿入したMarkdownは自前生成の文字列なので
                            どのチャンクに入ったか決定的に特定できる ─▶ chunk_id紐付け
埋め込み・Qdrant投入は既存のまま(アセットはベクトルに乗せない)
```

- `ParsedSection` / `ParsedDocument`(`core/ingestion/types.py`)にアセット情報を追加する
- 表のMarkdownは独立した段落としてセクション本文に挿入する。既存chunkerは `\n{2,}` で文単位分割するため表は1つの塊として扱われ、`target_max` を超える大きな表は単独チャンクになる(既存挙動をそのまま利用)
- 表領域のテキストブロックは本文から除外し、Markdown表で置換する(同一内容の二重取込を防ぐ)

## 5. データモデル

新テーブル `chunk_assets`(`core/storage/migrations.py` の既存パターンで追加):

| カラム | 型 | 内容 |
|---|---|---|
| id | TEXT PK | アセットID |
| source_id | TEXT | ソースID |
| chunk_id | TEXT nullable | 紐付くチャンク(表: Markdown挿入先の決定的特定 / 図: 同一ページのチャンク、複数該当時は先頭ord) |
| kind | TEXT | 'table' \| 'figure' |
| page | INTEGER | ページ番号(1-origin) |
| bbox | TEXT(JSON) | ページ上の領域 [x0,y0,x1,y1] |
| html | TEXT nullable | 表の完全HTML(結合セル・構造保持)。図はNULL |
| md_snippet | TEXT nullable | チャンク本文に挿入したMarkdown表(生成時置換の照合キー)。図はNULL |
| image_path | TEXT nullable | クロップPNGの相対パス。図は必須、表はNULL(v1では表の画像クロップは保存しない) |
| created_at | TEXT | 作成日時 |

- 画像ファイルは `data/assets/<source_id>/<asset_id>.png`(DBはパスのみ保持)。スライドPDF併産(`<id>.slides.pdf`)と同じ「ファイル+DB参照」のサイドカー方式
- ソース削除・再取込時は `chunk_assets` 行と `data/assets/<source_id>/` を一括削除する

## 6. 生成時の表HTML投入

- `core/generation/stream.py` のヒットチャンク組み立て時、表アセットを持つチャンクについて、本文中の `md_snippet` を **結合セルを含む表のみ** `html` に置換する(単純表はMarkdownのままでトークン節約)
- budgeter(`core/retrieval/budgeter.py`)は置換後のテキストをそのまま数えるため改修不要。置換によりトークンが増えた分は既存の段階的チャンク削減ロジックが吸収する
- MCPの `ask` は同じ生成経路を通るため自動的に恩恵を受ける。`find_quotes` は検索のみだが、チャンク本文にMarkdown表が入ることで検索精度自体が改善する

## 7. 再取込

- API: `POST /api/notebooks/{notebook_id}/sources/{source_id}/reingest`(202 Accepted)
- 処理: 保持済み原本(`sources_dir/<id>.<ext>`)を読み、既存チャンク(SQLite)・ベクトル(Qdrant)・アセット(DB行+ファイル)を削除してからpipelineを再実行する。status遷移(pending→parsing→chunking→embedding→ready)と進捗表示は既存のジョブ状態バーに乗る
- 取込処理中のソースへの再取込要求は409(状態競合)で拒否する
- 再取込で `chunk_id` は張り替わる。過去会話の引用バッジはチャンク解決失敗時に「ソース更新済み」の表示にフォールバックする(小改修)
- 埋め込みモデル切替時の再インデックス(既存機能)もpipelineを通るため、アセットは自動的に再生成される(削除→再構築で冪等)

## 8. UI(evaluatorスクショ検証ゲート対象)

- **再取込**: ソース行の既存コンテキストメニューに「再取込」を追加(新規ボタンを増やさず縦肥大化なし)。実行前に「チャンクと埋め込みを作り直します」の確認ダイアログ
- **表のHTML表示**: 引用スニペット(ホバー)とSource Viewerで、チャンクに紐付く表アセットがある場合にHTMLレンダリング表示する。表示前にsanitizeを適用する(自前生成のマークアップだが多層防御)
- 図クロップはStage 1では表示しない

## 9. エラー処理

既存のグレースフルデグレードパターン(recording extra未導入時の503+ヒント、PowerPoint COM縮退と同型)を踏襲する。

- 表検出・図抽出・ファイル保存の失敗は**ページ単位でログ+スキップ**し、取込自体は成功させる(アセットなしでも従来同等のテキスト取込は完了する)
- `find_tables()` の検出漏れ(罫線なし表など)は許容する。検出できた分だけ改善する方針
- アセットファイル欠損時(手動削除等)、生成時置換はスキップしMarkdownのまま投入、UI表示は非表示にフォールバックする
- 画像のみPDFの取込失敗は現状維持(エラーメッセージも既存のまま)

## 10. テスト

- **unit** (`tests/unit`):
  - パーサ: 罫線あり表/罫線なし表/結合セル表/画像入り/表なしのゴールデンPDFで抽出結果を検証
  - チャンク紐付け: 挿入Markdownとチャンクの対応が決定的であること、巨大表が単独チャンクになること
  - 生成置換: md_snippet→html置換の条件(結合セルの有無)とフォールバック
- **integration** (`tests/integration`):
  - fake ollamaでpipeline実行→chunk_assets行とファイルが生成されること
  - 再取込: 削除→再構築の冪等性、409競合、アセットの掃除
- **UI**: evaluator実機スクショで表HTMLレンダリング(引用ホバー/Source Viewer)と再取込フロー(メニュー→確認→ジョブ状態バー→完了)を検証

## 11. QAログ(推奨値で先行決定した非クリティカル論点)

| 論点 | 決定(推奨値) | 理由 |
|---|---|---|
| 表の本文表現 | Markdown、HTMLはサイドカー | 埋め込みのトークン効率 |
| 生成時HTML置換条件 | 結合セルを含む表のみ | 単純表はMarkdownで十分 |
| 図の対象 | ラスタ画像のみ。ページ面積0.5%未満の微小画像と全面背景は除外 | アイコン・背景ノイズ除去、ベクター線画はv1対象外 |
| クロップDPI | 150 | 表示・将来のVLM入力に十分 |
| 罫線なし表の検出漏れ | 許容(PyMuPDF検出分のみ) | 精度向上が必要ならDocling等を別Stageで判断 |
| アセット保存先 | `data/assets/<source_id>/<asset_id>.png` | ソース単位の一括削除が容易 |
| Qdrant非搭載 | アセットはベクトル化しない | 視覚埋め込みはStage 3の判断 |

## 12. 起票予定のADRドラフト(spec承認後に作成)

1. **チャンク紐付きアセットのサイドカー方式** — chunk_assets+ファイル保存、ベクトル非搭載、再取込=削除再構築(カテゴリ: データモデル/取込パイプライン)
2. **表の二重表現** — 本文Markdown=検索用 / サイドカーHTML=生成・表示用(カテゴリ: データ表現)

## 13. 参照

- 基盤設計: [[notebook-ollama-design]](原本保持・チャンク二重持ち・取込フロー)
- サイドカー前例: [[draft-2026-07-06-pptx-render-powerpoint-com]](取込時PDF併産+グレースフルデグレード)
- 再インデックス制約: [[2026-06-19-model-selection-design]]
- 進捗表示: [[2026-07-02-job-status-bar-optimistic-ui-design]]
- 調査対象: [PixelRAG](https://github.com/StarTrail-org/PixelRAG) / [Unlimited-OCR](https://github.com/baidu/Unlimited-OCR)
