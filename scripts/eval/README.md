# 検索精度オフライン評価

設計: [`docs/specs/2026-08-07-ragas-retrieval-eval-design.md`](../../docs/specs/2026-08-07-ragas-retrieval-eval-design.md)

開発者向けの実験ツール。製品UIからは参照されない。

## 準備

```bash
uv sync --extra eval --extra pdf --extra visual
```

`recording` extra は入れないこと。GPU 版 `visual` extra と cuDNN の CUDA
メジャーバージョンが衝突し、視覚索引が全滅する。

評価は本番と分離した環境で行う。専用の data_dir を指定し、8765 以外の
ポートを使うこと(この CLI 自体はサーバーを立てないが、同じ data_dir を
本番 uvicorn が掴んでいると Qdrant のローカルモードがロック衝突する)。

```bash
export NOTEBOOK_OLLAMA_DATA_DIR=./data/eval/workdir
```

これを**設定し忘れると CLI は停止する**(exit 2)。評価は data_dir に対して
ディレクトリ作成・DBマイグレーション・コレクション作成という書き込みを行うため、
本番 data_dir(`~/.notebook-ollama`)での実行は既定で拒否する。どうしても本番
data_dir で走らせる場合だけ `--allow-production-data-dir` を付ける。

## 手順

1. 評価コーパス(30ページ以内に切り出した図表多めの技術文書)を
   `data/eval/corpus/` に置き、`matrix.yaml` の `notebook_id` が指す
   ノートブックへ取り込む
2. 視覚索引 (page / tile) を baseline の格子で構築する
3. 設定でベータ機能 `table-figure-rag` を ON にする。OFF のままだと視覚検索が
   丸ごと無効化され、`search_strategy` / `index_unit` の軸が結果に一切効かない
   (全条件が同じテキスト検索になる)。この2軸のどちらかを `axes` に含む
   スイープは、視覚検索が無効なら CLI が停止する(exit 2)。無効の理由
   (ベータOFF / `visual` extra 未導入 / `visual.search_enabled` が false)は
   エラーメッセージに列挙される。視覚系の軸を振らないスイープでは警告のみ
4. golden set (`data/eval/golden.jsonl`) を作る。1行1問の JSONL で、形式は
   `core/eval/goldenset.py` の `GoldenItem` に対応する:

```json
{"id": "q1", "question": "…", "reference_contexts": ["正解チャンクの本文"], "kind": "table", "page_no": 12}
```

`kind` は `text` / `table` / `figure` のいずれか(種別ごとに指標を分解する)。

`scripts/eval/build_goldenset.py` が生成を半自動化する。

```bash
uv run --no-sync python scripts/eval/build_goldenset.py \
    --notebook-id <取り込み済みノートブックID> \
    --count 20 \
    --out data/eval/golden.jsonl
```

動作:

1. 対象ノートブックの取り込み済みチャンクを SQLite から読み出し、`--count`
   件(最低8件)をランダムにサンプリングする(`--seed` で再現可能)
2. **既定は Ragas 経路**。`ragas.testset.TestsetGenerator.from_langchain` に、
   ローカル Ollama を langchain-community の `ChatOllama` /
   `OllamaEmbeddings` でラップして渡し、サンプルしたチャンクから質問を
   生成させる。LLM は設定の `ollama.default_model`(`--llm-model` で上書き)、
   埋め込みは `ollama.embedding_model` を使う
3. 候補を1件ずつ端末に出し、`[y/N/q]` で採否を取る。採用したものだけ `kind`
   を入力して golden set に入る
4. `--out` に JSONL を書き出す。`q` や Ctrl-C で打ち切っても、そこまでの
   採用分は保存される。`--resume` を付けると既存ファイルの後ろに追記する
   (id は通し番号で振り直される)

**人手レビューを飛ばす経路は用意していない**(`--auto-accept` 等は無い)。
golden set は以降のすべての測定の土台なので、ローカルLLMが作った「正解」を
無検証で取り込むと、以降の数値が静かに間違い続ける。

### Ragas 経路の実測と限界

この環境(ragas 0.4.3 / Ollama)で `generate_with_chunks` は動作する。ただし:

- **遅い**。ナレッジグラフ構築(SummaryExtractor 等)が支配的で、実測で
  数十秒/チャンク。`--count 40` は1時間規模になりうる
- **質は当たり外れがある**。日本語コーパスに対して英語の質問が出る、本文を
  ほぼ言い換えただけの質問が出る、といった候補が混ざる。だから採否レビューが
  要る(そこで落とせばよい)

Ragas を使いたくない場合は `--manual` を付ける。質問生成を行わず、サンプル
したチャンク本文を提示して質問を人が書く半手動モードになる。品質ゲートである
人手レビューは同じように通るので、失うのは下書きの手間だけ。

```bash
uv run --no-sync python scripts/eval/build_goldenset.py \
    --notebook-id <id> --count 20 --out data/eval/golden.jsonl --manual
```

この CLI も `run_sweep.py` と同じ data_dir ガードを通る。
`NOTEBOOK_OLLAMA_DATA_DIR` が未設定だと本番 data_dir を指すため停止する
(exit 2)。

5. スイープを実行する

```bash
uv run --no-sync python scripts/eval/run_sweep.py \
    --matrix scripts/eval/example-matrix.yaml
```

結果は `docs/eval/retrieval/<date>-<name>/report.md` に出る。
`--dry-run` を付けると条件の展開結果だけを表示して終了する。

## 制約

- `tile_rows` / `tile_cols` / `tile_overlap` / `embedding_model` を `axes` に
  入れると索引の再構築が必要になり、CLI は実行を拒否する(exit 2)。索引構築は
  実測で約95秒/ページ(CPU 安全プロファイル)かかるため、無自覚な長時間実行を
  防ぐためのガード。これらを比較したい場合は、値ごとに索引を手動構築して
  baseline を差し替え、別々のスイープとして実行する
- 中断しても `results.jsonl` に完了済み条件が残るので、同じコマンドで再開できる
- 実行前ガードはすべて exit 2 で停止する: 本番 data_dir、視覚検索の無効、
  再インデックス要。`--dry-run` はこれらのガードの手前で終了するため、条件の
  展開結果だけを見たいときはいつでも使える
