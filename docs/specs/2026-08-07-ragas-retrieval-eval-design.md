---
type: spec
title: Ragas による検索精度オフライン評価基盤 — 設計仕様書
summary: "設定スイープで検索段の精度を定量比較するオフライン実験基盤。non-LLMメトリクス中心でjudge依存を排除し、タイル分割・視覚索引・埋め込みモデル・top_kの効果を数値で決着させる。"
aliases:
  - Ragas評価基盤
  - 検索精度評価
status: draft
date: 2026-08-07
project: NotebookOllama
area: evaluation
tags:
  - spec
  - evaluation
  - retrieval
code:
  - core/config.py
  - core/ingestion
  - core/retrieval
---

# Ragas による検索精度オフライン評価基盤 — 設計仕様書

## 1. 背景と目的

### 1.1 解決したい問題

本プロジェクトには検索精度の定量指標が存在しない。`docs/eval/` にあるのは Playwright による UI 検証レポートのみで、retrieval の recall / precision を測る仕組みは無い。

その結果、表・図RAG Stage 4 の効果測定は「タイル分割は一様に効かず、既定値は維持」という定性的な結論に留まった(コミット `38491c9`)。設定軸が増えるほど、根拠のない既定値が積み上がっていく。

### 1.2 目的

検索段の精度を設定条件ごとに数値比較できるオフライン実験基盤を作り、以下の設計判断を証拠付きで決着させる。

- タイル分割 (`tile_rows` / `tile_cols` / `tile_overlap`) は効くのか
- 視覚索引 (`search_strategy`) は素のテキスト検索に対して何ポイント寄与するか
- 埋め込みモデルを変えると検索精度はどう変わるか
- `top_k` の既定値は妥当か

### 1.3 位置づけ

**開発者向けオフライン評価ツール**である。製品UIには一切出さない。`core/retrieval` `core/ingestion` を含む既存の本番コードは改変しない。

## 2. 設計判断

### 2.1 Ragas の使い方 — メトリクス層のみ

Ragas のフレームワーク全体には乗らず、メトリクス計算にのみ使う。設定スイープと実行制御は自前で持つ。

**理由**: 本当に必要なのは「タイル分割は効くのか」という設計判断の決着であり、Ragas そのものではない。メトリクス層を薄く保てば、Ragas が期待外れだった場合に差し替えられる。Ragas の `EvaluationDataset` / testset generator / 統合APIに全面依存すると、ローカル埋め込みと Ollama のラッパー実装を抱え、Ragas のバージョン変更に追従し続けることになる。

**採用しなかった案**:
- Ragas フル活用 — 結合が強く、逃げ道がない
- Ragas 不使用・自前メトリクスのみ — 依存ゼロで最速だが、生成段評価に進む際に作り直しになる

### 2.2 評価対象 — 検索段のみ

context recall / context precision など retrieval の指標に限定する。faithfulness / answer relevancy といった生成段の指標は対象外。

**理由**: 1.2 で挙げた4つの設計判断は全て検索段に現れる。生成段まで含めると全メトリクスが judge LLM の質に依存し、judge が弱いとスコア自体が信用できなくなる(Stage 2 の VLM OCR モデル選定で 11GB VRAM 環境に実用モデルが無いと判明したのと同種の問題)。

### 2.3 判定方式 — non-LLM メトリクス中心

golden set に正解チャンク本文 (`reference_contexts`) を持たせ、文字列類似度ベースの `NonLLMContextRecall` / `NonLLMContextPrecisionWithReference` で採点する。LLM は golden set の候補生成時にしか登場しない。

**理由**: judge LLM の質がスコアを汚染するのを構造的に防ぐ。加えて再現性が高く、高速で、VRAM を消費しない。

### 2.4 golden set — 半自動生成 + 人手レビュー

Ragas の testset 生成で候補を作り、人間が採否をレビューして確定する。初回は30〜50問。

**理由**: 全手動は図表RAGの検証に必要な問数を揃えるのに時間がかかりすぎる。全自動はローカルLLMが生成した正解が誤っていても気づけず、誤った設計判断を誘発する。人手ゲートを挟むことで品質を担保する。

### 2.5 評価コーパス — 図表多めの技術文書1本

MCU データシートや Automotive SPICE PAM 4.0 のような、実際のユースケースに近い図表リッチな PDF を1本固定する。データは git 管理外 (`data/eval/`) に置く。

**理由**: 公開ベンチマークは他ツールとの比較はしやすいが、日本語・図表密度の高い組込み文書という実ユースケースと乖離する。複数文書ミックスは汎用性が上がる反面、golden set 作成コストとノイズが増える。

## 3. 既存資産との整合

| 資産 | 内容 | 本設計への影響 |
|---|---|---|
| [[014-visual-index-unit-collections\|ADR-014]] | 視覚索引の単位はコレクション分離 | 条件ごとにコレクション名へ条件ハッシュを含めれば、複数条件のインデックスを衝突なく並存できる |
| [[016-pixel-native-explicit-failure\|ADR-016]] | pixel-native 戦略は明示エラー | `search_strategy` を全値スイープすると環境次第で意図的に失敗する。ランナーは条件失敗を全体失敗にせず記録して継続する |
| [[017-torch-cuda-wheel-index\|ADR-017]] | visual extra の torch は CUDA ホイール | 評価環境は visual extra 側の venv で構築する |
| [[010-visual-index-qdrant-rrf\|ADR-010]] | 視覚索引は別コレクション + RRF 融合 | RRF の重みも将来のスイープ軸候補。今回は既定値固定 |

**環境上の既知制約**: recording extra と GPU 版 visual extra は cuDNN の CUDA メジャーバージョン衝突により共存できない。評価用 venv には recording extra を入れない。

**新規 ADR ドラフト**: 2.1(Ragas をメトリクス層に限定)と 2.3(non-LLM 判定)はアーキテクチャレベルの選択であるため、実装時に `docs/adr/drafts/` へドラフトを起票する。採番は承認後。

## 4. アーキテクチャ

### 4.1 配置

```
scripts/eval/
  run_sweep.py                 # スイープ実行 CLI
  build_goldenset.py           # golden set 半自動生成 CLI
core/eval/
  matrix.py                    # YAML → 条件の直積展開、再インデックス要否の仕分け
  runner.py                    # 1条件を実行して検索結果を集める
  metrics.py                   # Ragas non-LLM メトリクス + 自前 recall@k / MRR
  report.py                    # 条件別比較表の生成
docs/eval/retrieval/
  <date>-<sweep-name>/
    matrix.yaml                # 実行時の設定スナップショット
    results.jsonl              # 条件×質問ごとの生データ
    report.md                  # 比較表
data/eval/                     # gitignore
  corpus/                      # 評価コーパス PDF
  golden.jsonl                 # 確定済み golden set
```

`core/eval/` は「設定と検索結果を受け取ってスコアを返す」純粋層とし、`core/retrieval` `core/ingestion` には手を入れない。`core/config.py` が `tile_rows` / `tile_cols` / `tile_overlap` / `search_strategy` / `top_k` を全て設定値として保持しているため、スイープは設定オブジェクトの差し替えだけで成立する。

### 4.2 コンポーネントの責務

| モジュール | 責務 | 依存 |
|---|---|---|
| `matrix.py` | YAML 定義を条件リストへ展開。各条件に安定ハッシュを付与し、再インデックスが必要な条件群と検索時パラメータのみの条件群に仕分ける | なし(純粋関数) |
| `runner.py` | 1条件について、必要なら索引を構築し、golden set の全質問で検索を実行して `retrieved_contexts` を返す | `core.retrieval` / `core.ingestion`(読み取り利用のみ) |
| `metrics.py` | 質問ごとの `retrieved_contexts` と `reference_contexts` からスコアを算出 | `ragas` |
| `report.py` | 条件×メトリクスの比較表を markdown 化。既定値条件との差分を併記 | なし(純粋関数) |

### 4.3 依存の追加

`pyproject.toml` の optional-dependencies に `eval` extra を新設し、`ragas` をそこに入れる。本番インストールには含めない。

## 5. データフロー

### 5.1 golden set 構築(初回のみ)

```
コーパスPDF
  → 既定設定で ingest
  → Ragas testset 生成で Q&A 候補を作成
  → 人間が候補を採否レビュー
  → data/eval/golden.jsonl 確定
```

`golden.jsonl` の1行:

```json
{
  "id": "q001",
  "question": "SPI の送信 FIFO 深さは何段か",
  "reference_contexts": ["...正解チャンクの本文..."],
  "page_no": 412,
  "kind": "table"
}
```

`kind` は `text` / `table` / `figure` のいずれか。図表RAGの効果を種別ごとに分解して見るために持つ。

### 5.2 スイープ実行

```
matrix.yaml
  → matrix.py が条件を直積展開
  → 再インデックス要否で2群に仕分け
       検索時パラメータ群: 1インデックスを共有
       埋め込みモデル群  : 条件ごとに索引を再構築
  → 各条件 × 各質問で検索実行
  → results.jsonl へ逐次追記
```

`matrix.yaml` の例:

```yaml
name: tile-and-strategy
corpus: data/eval/corpus/sample.pdf
golden: data/eval/golden.jsonl
baseline: { tile_rows: 3, tile_cols: 1, search_strategy: hybrid_rrf, top_k: 8 }
axes:
  tile_rows: [1, 3, 5]
  search_strategy: [hybrid_rrf, visual_only]
  top_k: [5, 8, 12]
```

`baseline` は比較の基準となる条件。レポートで全条件をこの条件との差分として表示する。

### 5.3 採点とレポート

```
results.jsonl
  → metrics.py が条件ごとにスコア算出
  → report.py が比較表を生成 → report.md
```

## 6. メトリクス

| 指標 | 出所 | 何を見るか |
|---|---|---|
| context recall | Ragas `NonLLMContextRecall` | 正解チャンクを取りこぼしていないか(**主指標**) |
| context precision | Ragas `NonLLMContextPrecisionWithReference` | 上位に正解が来ているか(順位考慮) |
| recall@k | 自前 | 素の取りこぼし率。サニティチェック用 |
| MRR | 自前 | 最初の正解が何位に来るか |
| 検索時間 / 索引構築時間 | ランナー計測 | 精度が同点なら速い方を選ぶ判断材料 |

主指標を context recall とするのは、技術文書の調査という用途では「拾い漏れ」が「余分に拾う」より痛いため。

自前指標を併置するのは冗長に見えるが、Ragas の non-LLM メトリクスは文字列類似度の閾値に依存し、閾値設定を誤ると全条件が同スコアに潰れる。素の recall@k が動いていれば、それが計測バグなのか本当に差が無いのかを切り分けられる。

レポートは全体スコアに加えて `kind` 別(text / table / figure)の内訳を出す。タイル分割や視覚索引の効果は figure / table にのみ現れる可能性が高く、全体平均では埋もれるため。

## 7. エラー処理と実行制御

| 論点 | 方針 |
|---|---|
| 条件単位の分離 | 1条件が落ちても記録して次へ進む。ADR-016 の意図的エラーや OOM を全体失敗にしない。失敗条件はレポートに理由付きで明示する |
| 中断耐性 | `results.jsonl` へ逐次追記。再実行時は完了済み条件をスキップして再開する |
| 隔離実行 | 専用 `data_dir` と 8765 以外のポートを使う。本番サーバーには一切アクセスしない |
| 設定スナップショット | 実行時の全設定を `matrix.yaml` として結果ディレクトリに保存し、後から条件を復元できるようにする |
| 実行時間の警告 | 埋め込みモデル軸を含むスイープは開始前に「再インデックスが N 回発生する」旨を表示し、確認を求める |

## 8. テスト

`core/eval/` を純粋層としたため、検索を実行せずにユニットテストできる。

| 対象 | テスト内容 |
|---|---|
| `matrix.py` | YAML → 条件展開が正しいか。再インデックス要否の仕分けが正しいか。条件ハッシュが安定しているか |
| `metrics.py` | 既知の入出力(完全一致 / 全外し / 部分一致)で期待値どおりのスコアになるか |
| `report.py` | 比較表の生成、baseline との差分計算、失敗条件の表示 |
| `runner.py` | 検索サービスをフェイクに差し替え、条件失敗時に継続するか、再開が完了済み条件をスキップするか |

実データを使う統合テストは1条件×3質問の最小構成とし、CI ではなくローカル手動実行とする。

新規エントリポイント (`run_sweep.py` / `build_goldenset.py`) は pytest 全通過をもって完了とせず、実際に起動して動作を確認する。

## 9. スコープ外

| 項目 | 理由 |
|---|---|
| 生成段の評価(faithfulness 等) | judge LLM 依存を避けるため今回は入れない。`metrics.py` に追加できる余地だけ残す |
| Web UI での結果表示 | オフラインツールであり markdown で足りる |
| CI への品質ゲート組み込み | ベースラインが取れてから別途判断する |
| 自動チューニング(最適設定の探索) | まず人間が比較表を見て決める |
| RRF 重みのスイープ | 今回は既定値固定。将来の軸候補 |

## 10. 完了条件

1. `matrix.yaml` を書いて `run_sweep.py` を実行すると、条件別比較表が `docs/eval/retrieval/` 配下に生成される
2. golden set が30問以上あり、`kind` 別の内訳が text / table / figure すべてに存在する
3. タイル分割 on/off の比較結果が数値で出ており、Stage 4 の保留事項に結論を出せる
4. `core/eval/` のユニットテストが全通過し、両CLIの実機起動を確認済み
5. 2.1 / 2.3 の設計判断が ADR ドラフトとして起票されている
