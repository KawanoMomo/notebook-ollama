---
type: spec
title: 視覚埋め込み第2インデックス (Stage 3)
summary: "PDFページ全体を視覚埋め込み(Qwen3-VL-Embedding)でQdrant別コレクションに索引し、テキスト検索とRRF融合する。PixelRAG式視覚検索のローカル適用。"
aliases:
  - 視覚インデックス
  - visual-embedding-index
status: approved
date: 2026-07-20
project: NotebookOllama
area: retrieval
tags:
  - spec
  - retrieval
  - rag
  - visual
related:
  - "[[2026-07-20-pdf-table-figure-sidecar-design]]"
  - "[[2026-07-20-vlm-figure-ocr-design]]"
  - "[[2026-06-19-model-selection-design]]"
  - "[[2026-07-20-beta-feature-flags-design]]"
---

# 視覚埋め込み第2インデックス (Stage 3) 設計書

## 1. 背景と目的

Stage 1/2 はテキスト化できるものを検索に乗せる改善だが、「レイアウト・図表・視覚構造ごと検索する」PixelRAG のアプローチはテキスト化を経ずにページを画像のまま索引する。Stage 3 はこれを第2インデックスとしてローカル(RTX 2080 Ti 11GB)に適用し、テキスト検索が拾えないページ(図主体・複雑レイアウト)を補完する。**実験枠**であり、Stage 1/2 の効果測定後に着手判断する。

## 2. スコープ

### 対象 (in)

- PDFページ全体の視覚埋め込み(1ページ=1ベクトル)による第2インデックス
- テキスト検索との RRF(Reciprocal Rank Fusion)自動融合
- 生成時: チャットモデルがVLMならヒットページ画像を投入(Stage 2 の late-binding 機構を再利用)
- ノートブック単位の手動「視覚インデックス構築」

### 対象外 (out)

- PDF以外のフォーマットの視覚索引(pptxはスライドPDF併産があるため将来の有力候補として付記)
- アセット(表・図クロップ)単位の視覚埋め込み(ページ単位で当たればその中に含まれる)
- 視覚検索専用UI(検索は既存チャットに透過統合)
- FAISS(インデックスはQdrantに統一)

## 3. 確定済み判断(ユーザー合意)

| 論点 | 決定 |
|---|---|
| 埋め込み対象 | ページ全体(PixelRAG本来の思想。原本保持済みなので再取込不要でレンダリング可能) |
| 検索統合 | RRF自動融合。UI不変、視覚インデックス未構築ノートブックは自動スキップ、設定でOFF可 |
| 提供形態 | ベータ(シリーズ共通フラグ `table-figure-rag`、既定OFF、[[2026-07-20-beta-feature-flags-design]]) |

## 提供形態(ベータ) — フラグOFF時の挙動

本機能は `table-figure-rag` フラグ(表・図シリーズ共通)配下のベータ機能として提供する。

- **OFF時**: RRF融合はスキップし従来のテキスト検索のみ。ノートブック設定の「視覚インデックス」セクションは非表示、構築/削除APIは403+有効化ヒント
- **構築済みデータ**: pages_visual コレクション・ページPNG・visual_index_meta はOFF後も保持され、ONに戻せばそのまま利用再開できる

## 4. アーキテクチャ

```
[構築(手動、ノートブック単位)]
原本PDF ─▶ ページレンダリング(PNG) ─▶ Qwen3-VL-Embedding(transformers, fp16)
        ─▶ Qdrant別コレクション pages_visual (1ページ=1ベクトル, payload: source_id/page/model)
        └─▶ ページPNGは data/assets/<source_id>/pages/<page>.png に保存(ヒット時のVLM投入用)

[検索時]
クエリテキスト ─▶ 同モデルのテキストエンコーダで埋め込み ─▶ pages_visual top-k
既存テキスト検索 top-k ─┐
                        ├─▶ RRF融合 ─▶ ページヒットは該当ページのチャンク群+ページ画像に展開
                        └─▶ 既存 budgeter → 生成(VLMならページ画像投入、非VLMはチャンクテキストのみ)
```

- 視覚埋め込みは Ollama 非対応のため **transformers スタックで実行**する。`uv sync --extra visual` のオプション依存とし、未導入時は機能全体を503+導入ヒントで縮退(recording extra と同型)
- モデルは常駐させず**オンデマンドロード+アイドルアンロード**(タイムアウトで解放)。クエリ時のテキスト埋め込みにも同モデルが必要なため、視覚検索ONのノートブックで最初のクエリはロード時間(数秒)を許容する

## 5. データモデル

- Qdrant コレクション `pages_visual`: ベクトル+payload(`source_id` / `page` / `embedding_model` / `built_at`)
- SQLite `visual_index_meta`(ノートブック単位): 構築済みモデル名・構築日時・対象ソース数(モデル不一致の検知と再構築判断に使用)
- ページPNG: `data/assets/<source_id>/pages/<page>.png`(ソース削除・再取込で一括削除、Stage 1 の掃除機構に相乗り)

## 6. 検索融合の詳細

- RRF は標準の k=60。テキストヒット(チャンク)と視覚ヒット(ページ)を統合し、ページヒットは「そのページに属する先頭2チャンク」として budgeter に流す(チャンクが無いページ=スキャン未OCRページは説明なしのページ画像のみ)
- 同一ページにテキスト・視覚の両方でヒットした場合は重複排除(視覚側を吸収)
- 引用はページ単位表示(「p.42(視覚検索)」)。Source Viewer のページ送りにジャンプ
- 視覚検索の実行条件: 設定ON かつ 対象ノートブックの `visual_index_meta` が存在 かつ extra導入済み。いずれか欠ければ従来のテキスト検索のみ(挙動変化なし)

## 7. VRAM / リソース運用

- Qwen3-VL-Embedding-2B を fp16 で約4〜5GB。Ollama のチャットLLMと同時常駐は11GBでは不安定なため、**構築時とクエリ時のみロード→アイドルアンロード**(既定5分)
- 構築はジョブ状態バーに乗せ、進捗(ページ数ベース)を表示。構築中のチャットは従来のテキスト検索で動作継続
- CUDA不可の環境では CPU 推論にフォールバック(遅いが機能は維持。構築時に所要時間目安を表示)

## 8. API / UI(evaluatorスクショ検証ゲート対象)

- API: `POST /api/notebooks/{notebook_id}/visual-index`(202、構築/再構築。モデル不一致時は全再構築)
- API: `DELETE /api/notebooks/{notebook_id}/visual-index`(コレクション該当分+メタ削除。ページPNGは残す)
- UI: ノートブック設定画面に「視覚インデックス」セクション(構築ボタン・状態表示・削除)。チャット画面には何も追加しない
- 設定: 「視覚検索を使う」トグル(既定ON。実行条件は§6のとおり構築済みノートブックのみ)

## 9. エラー処理

- extra未導入: 503+`uv sync --extra visual` のヒント(既存パターン)
- 構築中のソース追加/再取込: 構築完了後のソースは未索引として `visual_index_meta` に差分数を表示、「視覚インデックス構築」の再実行で追補(差分のみ)
- ページレンダリング・埋め込みの失敗はページ単位でログ+スキップ、構築は継続(部分成功)
- クエリ時のモデルロード失敗: 視覚検索をスキップしテキスト検索のみで応答(エラーにしない、dev_logsに記録)

## 10. テスト

- **unit**: RRF融合(順位・重複排除・ページ→チャンク展開)、実行条件判定(設定/メタ/extra の組合せ)、アンロードタイマー
- **integration**: fake埋め込み(固定ベクトル)で構築→pages_visual投入→検索融合、差分追補、削除、部分失敗継続
- **UI**: evaluator実機スクショで構築フロー(ボタン→ジョブ状態バー→完了)、視覚ヒットの引用表示(ページ単位)
- **実機性能**: 2080 Ti で代表PDF(50ページ)の構築時間・クエリ遅延・VRAM実測を計測しspecの想定と突き合わせる(runtime verification gate)

## 11. QAログ(推奨値で先行決定した非クリティカル論点)

| 論点 | 決定(推奨値) | 理由 |
|---|---|---|
| インデックス基盤 | Qdrant別コレクション(FAISS不採用) | 既存基盤の再利用、運用一元化 |
| 埋め込みモデル | Qwen3-VL-Embedding-2B(fp16) | PixelRAG採用モデル、11GBで動作見込み |
| モデル実行 | transformers + `--extra visual`、オンデマンドロード+5分アイドルアンロード | Ollama非対応機能の最小追加、VRAM共存 |
| ページレンダリングDPI | 100(埋め込み用)。VLM投入時も同画像を使用 | 埋め込みは高DPI不要、ストレージ節約 |
| RRF定数 | k=60 | 標準値、チューニングは実測後 |
| 構築トリガ | ノートブック単位の手動 | 実験枠のコスト明示制御(Stage 1再取込と同思想) |
| 視覚埋め込みモデルの切替 | 再構築必須(メタのモデル名不一致で検知) | テキスト側の再インデックス制約と同型 |

### 実装時の逸脱・実測記録(2026-07-26、詳細はADRドラフト visual-embedding-ondemand-transformers)

| 論点 | 実装結果 | 理由 |
|---|---|---|
| モデル実行API | sentence-transformers(素のAutoModel不採用) | モデルの正規API。素のforwardは画像単独入力不可(実機確認) |
| CPU dtype | bfloat16(fp32不採用) | fp32は常駐8-9GBでサーバーOOM即死(実機2回)。bf16でRSS 4.5GB一定 |
| §7のfp16/CUDA前提 | CPUフォールバックが実質既定 | PyPIのWindows torchはCPU-only。CUDA(cu126)はsm_75対応だがOllama常駐下でWDDMスピルによりCPUより遅く、11GB同時常駐は不成立(§7の警告を実測確認) |
| 負荷ノブ(新設) | build_cooldown_seconds=10 / cpu_threads=4 / cpu_prefer_performance_cores=True を既定 | 全力プロファイル(全24スレッド)は実機50ページ構築でBSOD(0x7F_8)2回。8スレッドはEcoQoSでE-core 8基に載り100%飽和→ブラウザ背景処理がカクつく(実機FB)。既定はEcoQoS解除+4スレッドでP-coreへ分業(E-core完全解放、実測105秒/ページ) |
| P/E分配の実測 | 均等混載は不採用 | fork-join並列は遅いE側が律速。またbf16エミュレーションはメモリ帯域律速でP-coreの1スレッド速度はEと同等(4P=105s/頁 vs 8E=53s/頁)。速度優先時は cpu_threads=8(P8基、電力増)へ設定変更 |
| 所要時間目安表示 | Modal内に「残り目安 約N分」(観測ペースから算出) | CPU実測52秒超/ページで目安の実用価値が高い(evaluator指摘で追補) |

## 12. 起票予定のADRドラフト(spec承認後に作成)

1. **視覚インデックスはQdrant別コレクション+RRF融合** — 第2インデックスの置き場所と統合方式(カテゴリ: アーキテクチャ/検索)
2. **視覚埋め込みはOllama外(transformers)でオンデマンド実行** — extra化・アイドルアンロード・11GB共存戦略(カテゴリ: 外部依存/リソース管理)

## 13. 参照

- 前段: [[2026-07-20-pdf-table-figure-sidecar-design]] / [[2026-07-20-vlm-figure-ocr-design]]
- 制約の同型: [[2026-06-19-model-selection-design]](切替=再インデックス)
- 調査対象: [PixelRAG](https://github.com/StarTrail-org/PixelRAG)(ページ画像検索+VLM読解の思想、Qwen3-VL-Embedding採用例)
