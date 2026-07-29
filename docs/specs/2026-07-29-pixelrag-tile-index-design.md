---
type: spec
title: PixelRAG式タイル索引と検索戦略の選択 (Stage 4)
summary: "視覚索引の単位(ページ/タイル)と検索戦略(RRF融合/視覚のみ/pixel-native)を設定から選択可能にし、PixelRAG方式を実験的アプローチその2として現行方式と並置する。第1スプリントでtorchのCUDA化を行う。"
aliases:
  - タイル索引
  - pixelrag-tile-index
  - 実験的アプローチその2
status: draft
date: 2026-07-29
project: NotebookOllama
area: retrieval
tags:
  - spec
  - retrieval
  - rag
  - visual
related:
  - "[[2026-07-20-visual-embedding-index-design]]"
  - "[[2026-07-20-vlm-figure-ocr-design]]"
  - "[[2026-07-20-pdf-table-figure-sidecar-design]]"
  - "[[2026-07-20-beta-feature-flags-design]]"
---

# PixelRAG式タイル索引と検索戦略の選択 (Stage 4) 設計書

## 1. 背景と目的

Stage 3 で視覚埋め込み第2インデックス(`pages_visual`)を実装し、テキスト検索とのRRF融合まで通した。その後、Berkeley Sky Computing Lab らの [PixelRAG](https://github.com/StarTrail-org/PixelRAG)(Apache-2.0)を調査したところ、Stage 3 と同じ思想でありながら2点で異なることが分かった。

| 論点 | Stage 3 実装 | PixelRAG |
|---|---|---|
| 索引単位 | 1ページ = 1ベクトル | タイル分割(約3.6タイル/ページ) |
| 検索 | テキスト検索とRRF融合 | 視覚のみ(pixel-native) |
| 埋め込み | Qwen3-VL-Embedding-2B | Qwen3-VL-Embedding-2B + スクショ特化LoRA |
| リーダー | ページ画像を late-binding 投入 | 画像タイルを VLM に投入 |

埋め込みモデルとリーダー側は既に一致している。実質的な差分は**索引単位**と**検索戦略**の2つに絞られる。

本 Stage の目的は、この2つを設定から選択可能にし、**現行方式(方式A)を既定として温存したまま、PixelRAG方式(方式B)を実験的アプローチその2として並置**することである。どちらが自分の資料に効くかを実測で決められる状態を作る。

### 1.1 調査で判明した前提条件の誤り

設計中に、視覚埋め込みが GPU を一切使っていないことが判明した。

```
torch 2.13.0+cpu   cuda_available False   cuda_build None
```

`--extra visual` が導入している torch は PyPI 既定の **CPU専用ホイール**である。RTX 2080 Ti (11GB) は視覚埋め込みに使われていない。`VisualSettings` に積み上がっている `build_cooldown_seconds=10.0` / `cpu_threads=4` / `cpu_prefer_performance_cores=True`、および実測値「約95秒/ページ」と長時間構築中の BSOD 観測は、すべて CPU 推論を成立させるための対症療法である。

タイル分割は1ページあたりの埋め込み回数を約3倍にするため、CPU のままでは1ページ5分弱となり比較実験が回らない。**torch の CUDA 化を本 Stage の第1スプリントに含める**(§8)。

## 2. スコープ

### 2.1 含むもの

- 視覚索引の**単位**を `page` / `tile` から選択(両方の索引を同時保持)
- **検索戦略**を `hybrid_rrf` / `visual_only` / `pixel_native` から選択
- タイル分割の純関数と、そのパラメータ(行数・列数・オーバーラップ)の設定化
- 単位ごとに独立した索引構築・状態表示・削除
- `--extra visual` の torch を CUDA ホイールへ差し替え、実機ゲートで検証
- 設定画面と視覚インデックス Modal の対応する UI 変更

### 2.2 含まないもの

- PixelRAG パッケージ本体の導入(Playwright + poppler + FAISS 前提。既存の PyMuPDF + Qdrant と二重になる)
- スクリーンショット特化 LoRA アダプタの適用(Wikipedia ドメイン特化であり、日本語技術文書との適合は未知。効果測定後に別途判断)
- ブラウザレンダリング(CDP)によるページ画像生成。PyMuPDF レンダリングを継続する
- PDF 以外のソース種別への視覚索引
- 方式A/方式Bの回答を並べて表示する比較専用UI(設定を切り替えて同じ質問を再送する運用で足りる)

## 3. 用語

| 用語 | 定義 |
|---|---|
| 方式A | 現行方式。索引単位 = ページ、検索戦略 = RRF融合 |
| 方式B | PixelRAG方式。索引単位 = タイル、検索戦略 = 視覚のみ または pixel-native |
| 単位 (unit) | 視覚ベクトル1本が対応する画像領域。`page` または `tile` |
| タイル | ページ画像を格子状に分割した部分画像。オーバーラップを持つ |
| pixel-native | プロンプトにテキストを一切載せず、画像のみを VLM に渡す検索戦略 |

## 4. 設定モデル

`core/config.py` の `VisualSettings` に6フィールドを追加する。**既定値はすべて現行の挙動と一致する**ため、設定を変更しない限り Stage 3 からの振る舞いの変化はない。

```python
class VisualSettings(BaseModel):
    # ... 既存フィールド (embedding_model, search_enabled, idle_unload_seconds,
    #     render_dpi, build_cooldown_seconds, cpu_threads,
    #     cpu_prefer_performance_cores) はそのまま ...

    # 検索に使う視覚索引の単位。"page" = 現行(1ページ1ベクトル)、
    # "tile" = PixelRAG式(ページをタイル分割して各タイルを1ベクトル)。
    # 両方の索引を同時保持できるため、切替に再構築は不要。
    index_unit: Literal["page", "tile"] = "page"

    # 検索戦略。§6 参照。
    search_strategy: Literal["hybrid_rrf", "visual_only", "pixel_native"] = "hybrid_rrf"

    # タイル分割の格子。既定は縦3分割・列分割なし。
    tile_rows: int = 3
    tile_cols: int = 1
    # 隣接タイルの重なり率(タイル1辺に対する比)。分割線が表や図を跨いだ
    # ときに、両側のタイルへ手掛かりを残すためのマージン。
    tile_overlap: float = 0.1

    # pixel_native 戦略でVLMに渡す画像の最大枚数。他の戦略では現行どおり
    # 2枚上限を使う(§7.3)。タイルはページ全体より小さくトークン消費が
    # 少ないため、pixel_native ではより多く積める。
    max_images: int = 4
```

既存の `search_enabled`(視覚検索を使うか)は変更しない。OFF のときは `index_unit` / `search_strategy` の値によらずテキスト検索のみになる。

`pixel_native` のときの画像枚数上限は §7 の `max_images` で扱う。

## 5. ストレージ

### 5.1 コレクションの一般化

`core/storage/visual_store.py` の `VisualPageStore` を、コレクション名と単位を受け取る `VisualUnitStore` に一般化する。

```python
class VisualUnitStore:
    def __init__(self, *, client: QdrantClient, collection_name: str, unit: str) -> None: ...
```

- `pages_visual` (unit=`page`) と `tiles_visual` (unit=`tile`) の2インスタンスを構築する
- Qdrant ローカルモードの1パス1クライアント制約のため、`QdrantClient` は既存 `VectorStore.client` を共有する(Stage 3 と同じ)
- `PageVector` / `PageHit` を `UnitVector` / `UnitHit` に改名し、`tile_index: int | None` を追加する

### 5.2 point ID 書式

```
unit=page : uuid5(NS, f"visualpage:{source_id}:{page}")            # Stage 3 と同一
unit=tile : uuid5(NS, f"visualtile:{source_id}:{page}:{tile_index}")
```

`unit=page` の書式を維持することにより、**既に構築済みの `pages_visual` は再構築不要**である。

### 5.3 メタデータ

`visual_index_meta` / `visual_index_sources` に `unit` 列を追加し、主キーを複合キーに変更する。

| テーブル | 変更前 PK | 変更後 PK |
|---|---|---|
| `visual_index_meta` | `notebook_id` | `(notebook_id, unit)` |
| `visual_index_sources` | `source_id` | `(source_id, unit)` |

SQLite は PRIMARY KEY の変更をサポートしないため、マイグレーションは「新テーブル作成 → 既存行を `unit='page'` として INSERT SELECT → 旧テーブル DROP → RENAME」の手順を取る。冪等にするため、既に `unit` 列があれば何もしない。

これにより、ページ索引とタイル索引の構築状態(どのソースが索引済みか、どのモデルで構築したか)を独立に管理できる。

### 5.4 ページ画像・タイル画像の保存

```
assets/<source_id>/pages/<page>.png            # 既存(Stage 3)
assets/<source_id>/tiles/<page>-<tile>.png     # 新規
```

タイル画像は引用クリック時の表示と、`pixel_native` での VLM 投入に使う。ソース削除時は `assets/<source_id>` ごと消えるため、既存の掃除処理で自動的にカバーされる。

## 6. タイル分割

新規モジュール `core/visual/tiling.py` に純関数として実装する。副作用を持たず、PIL のみに依存する。

```python
@dataclass
class Tile:
    index: int
    png: bytes

def split_tiles(png: bytes, *, rows: int, cols: int, overlap: float) -> list[Tile]: ...
```

### 6.1 既定値の根拠

既定は `rows=3, cols=1, overlap=0.1`(縦3分割・オーバーラップ10%)。

- PixelRAG は Wikipedia 8.28M ページを 30M タイルに分割しており、約3.6タイル/ページ。縦3分割はこれに近い
- A4 縦の技術文書は情報が縦方向に積層するため、列分割より行分割が効く。2段組の資料に対しては `tile_cols` で列分割できる
- オーバーラップは、分割線が表や図を横切ったときに両側のタイルへ手掛かりを残すためのマージン。0 だと境界上の要素がどちらのタイルからも読み取れなくなる

これらは**実測で調整することを前提とした出発点**であり、設定で変更できる。

### 6.2 分割規則

- `rows × cols` 個のタイルを、左上から行優先で `index=0..n-1` を割り当てる
- 各タイルの基準サイズは `(W/cols, H/rows)`。そこから上下左右に `overlap × 基準辺長` を広げ、画像境界でクリップする
- 端数ピクセルは最終行・最終列に寄せる(切り捨てによる画素の欠落を防ぐ)
- `rows=1, cols=1` は分割なしと等価であり、ページ画像そのものを返す

### 6.3 縮退

タイル基準サイズが 32px 未満になる場合(極端に小さいページ)、分割せずページ画像1枚を `index=0` として返す。埋め込みモデルの最小入力を下回る画像を作らないため。

## 7. 検索と生成

### 7.1 検索戦略

`core/retrieval/search.py` の `RetrievalService.search()` を `search_strategy` で分岐させる。視覚検索は `index_unit` で選ばれたコレクションに対して行う。

| 戦略 | 候補選定 | プロンプト本文 | 備考 |
|---|---|---|---|
| `hybrid_rrf` | テキスト検索 + 視覚検索 → RRF融合(k=60) | 従来どおり | Stage 3 の現行挙動。既定 |
| `visual_only` | 視覚検索のみ | ヒット単位が属するページの先頭2チャンクに展開 | テキスト埋め込み検索を呼ばない |
| `pixel_native` | 視覚検索のみ | **載せない** | 画像のみを VLM に渡す |

`visual_only` はテキスト検索を実行しないため、「テキスト検索と視覚検索のどちらが当てているか」を混ぜずに比較できる。既存のページ→チャンク展開機構をそのまま流用する。

`pixel_native` では `RetrievedChunk.text` を空文字列とし、引用表示用のロケーション文字列のみを持たせる。budgeter には空文字が流れるため、トークン配分は実質的に画像枠のみになる。

### 7.2 引用表記

| 単位 | 表記 |
|---|---|
| page | `p.3(視覚検索)` — 既存 |
| tile | `p.3 タイル2(視覚検索)` |

`core/generation/locations.py` の `format_location` を拡張する。

### 7.3 画像投入

現行は「図クロップ + ページ画像を合算2枚上限」。これを戦略別にする。

| 戦略 | 画像上限 |
|---|---|
| `hybrid_rrf` / `visual_only` | 2枚(現行のまま) |
| `pixel_native` | `max_images`(既定4) |

タイルはページ全体より小さくトークン消費が少ないため、`pixel_native` ではより多く積める。`max_images` は `VisualSettings` に追加する。

### 7.4 pixel_native と vision 非対応モデル

`pixel_native` は、プロンプト本文が空であるため、画像が渡らなければモデルは**何の根拠もないまま回答を生成してしまう**。これは黙って劣化させてはいけない失敗である。

したがって `search_strategy == "pixel_native"` かつ選択中のチャットモデルが vision capability を持たない場合、`AppError(ErrorCode.INPUT_INVALID)` で明示的に失敗させる。

```
message:     pixel-native 検索には視覚対応のチャットモデルが必要です
remediation: 設定画面でチャットモデルを vision 対応のもの(qwen3-vl 系など)に
             変更するか、検索戦略を「視覚のみ」または「RRF融合」に戻してください。
```

判定には Stage 2 で実装済みの `probe_vision_capability` を再利用する。

Stage 2 で「11GB 環境に実用 OCR モデルが存在しない」ことを品質ガードで明示エラー化した判断と同じ扱いである。**`pixel_native` は現時点の 11GB 環境では実用にならない可能性が高いが、選択肢としては用意する**。将来モデル事情が変われば設定を切り替えるだけで検証できる。

## 8. torch の CUDA 化

### 8.1 変更

`pyproject.toml` の `visual` extra が導入する torch を CUDA ホイールに差し替える。`[tool.uv.sources]` で PyTorch の CUDA インデックスを指定する。CPU 環境でも動くよう、CUDA が使えない場合は既存の CPU 経路にフォールバックする(`core/visual/encoder.py` は既に `torch.cuda.is_available()` で分岐しているため、コード変更は不要)。

### 8.2 実機ゲート(受入条件)

RTX 2080 Ti は Turing (sm_75) であり、選んだ CUDA ビルドが sm_75 カーネルを含むかは**実際に埋め込みを1枚流すまで確定しない**。以下をすべて満たすことをゲートとする。

1. `torch.cuda.is_available()` が `True` を返す
2. 実ページ1枚の埋め込みが例外なく完了する(`no kernel image is available for execution on the device` が出ないこと)
3. ページ/秒 と VRAM 使用量を実測し、spec の QAログに記録する
4. チャットモデルと同時常駐した状態で OOM しない(アイドルアンロード機構が既にあるため、構築中にチャットを1往復して確認する)

### 8.3 通った場合の副次効果

`build_cooldown_seconds` / `cpu_threads` / `cpu_prefer_performance_cores` は既に `device == "cpu"` の分岐内にあるため、コード変更なしで自動的に無効化される。これらの既定値は CPU フォールバック用として残す。

### 8.4 通らなかった場合

CPU 推論を維持したまま、タイル分割の既定を `tile_rows=2` に落として着地させる。この場合、方式Bの構築コストはページあたり約2倍(現行実測 約95秒/ページ からの推定で 約190秒/ページ)となり、比較実験は小規模ノートブックに限定される。**この縮退は spec に明記された想定内の着地点であり、失敗ではない。**

## 9. UI

### 9.1 設定画面

ベータ機能欄の既存の視覚設定項目の並びに `<select>` を2つ追加する。

- 索引単位: `ページ全体` / `タイル分割`
- 検索戦略: `RRF融合(テキスト+視覚)` / `視覚のみ` / `pixel-native(画像のみ)`

既存の項目リストへの追加のみで、画面の縦方向の肥大化は最小に留まる。

タイル分割のパラメータ(`tile_rows` / `tile_cols` / `tile_overlap`)は設定ファイル経由のみとし、UI には出さない。実測で詰める調整用のノブであり、常用の操作ではないため。

### 9.2 視覚インデックス Modal

現在1ブロックの構築UIを**2行**にする。各行に「構築状態(構築済みソース数 / ページ数 / モデル名 / 構築日時)」「構築ボタン」「削除ボタン」を持たせる。

```
ページ索引   構築済み 3ソース / 47ページ (Qwen3-VL-Embedding-2B, 07-26)   [構築] [削除]
タイル索引   未構築                                                        [構築] [削除]
```

タブではなく2行にするのは、**両方の構築状態を同時に見せるため**である。どちらの索引で比較しているのか分からなくなるのが、この機能で最も起きやすい混乱である。

削除は Stage 3 で導入した2段階確認をそのまま踏襲する。

### 9.3 検証

UI変更を含むため、evaluator による実機スクリーンショット検証の PASS を完了条件とする。自動テストの GREEN のみでは visual regression を検出できない。

## 10. エラー処理と縮退

| 状況 | 挙動 |
|---|---|
| ベータフラグ `table-figure-rag` OFF | 従来のテキスト検索のみ。構築済みデータは保持し、ON で再開 |
| `--extra visual` 未導入 | 視覚関連APIは 503 + `uv sync --extra visual` ヒント。検索はテキストのみに自動縮退 |
| 選択中 unit の索引が未構築 | `hybrid_rrf` / `visual_only` はテキスト検索へ自動縮退(既存挙動)。`pixel_native` は縮退できないため明示エラー |
| `pixel_native` × vision 非対応モデル | 明示エラー(§7.4) |
| タイル分割失敗(極小ページ) | ページ画像1枚にフォールバックしてログ、構築は継続(§6.3) |
| 構築中の再構築要求 | 202 + `{"status": "already_building"}`。単一飛行キーは `(notebook_id, unit)` |
| ページ単位の埋め込み失敗 | ログ + スキップで構築継続(部分成功。Stage 3 と同じ) |

## 11. テスト方針

| 対象 | 方針 |
|---|---|
| `split_tiles` | 純関数の単体テスト。分割数・オーバーラップ量・端数の寄せ・極小画像の縮退 |
| `VisualUnitStore` | 既存 `test_visual_store.py` を page/tile でパラメトライズして拡張 |
| マイグレーション | 既存 `visual_index_meta` 行が `unit='page'` として移行されること、冪等であること |
| 検索戦略3種 | Fakeエンコーダによる統合テスト。実モデルに依存しない |
| `pixel_native` ガード | vision 非対応モデル選択時にエラーになる統合テスト |
| 引用表記 | `format_location` の単体テスト(page / tile) |
| CUDA化 | 自動テストでは担保不可。§8.2 の実機ゲートを受入条件とする |
| UI | evaluator 実機スクリーンショット |

実モデル(`Qwen/Qwen3-VL-Embedding-2B`)への依存は Stage 3 と同様 `core/visual/encoder.py` の1ファイルに閉じ込め、それ以外は `VisualEncoder` Protocol の Fake で差し替え可能にする。

## 12. ADR ドラフト候補

本 Stage の設計判断のうち、アーキテクチャレベルのものは `docs/adr/drafts/` にドラフトを残す。

| 論点 | 判断 |
|---|---|
| 視覚索引の単位選択 | 単一コレクションに unit payload を持たせるのではなく、単位ごとに別コレクションを持ち同時保持する |
| pixel-native の失敗の扱い | vision 非対応モデルでは黙って縮退せず明示エラーにする |
| torch の CUDA 化 | `--extra visual` を CUDA ホイールに切り替え、CPU はフォールバック経路として残す |

## 13. QAログ(推奨値で先行決定した非クリティカル論点)

| 論点 | 決定 | 理由 |
|---|---|---|
| タイル分割の既定値 | `rows=3, cols=1, overlap=0.1` | PixelRAG の約3.6タイル/ページに近く、A4縦文書は縦方向に情報が積層する。実測で調整する前提 |
| タイルパラメータのUI露出 | しない(設定ファイルのみ) | 調整用ノブであり常用操作ではない。設定画面の肥大化を避ける |
| `pixel_native` の画像上限 | 既定4枚 | タイルはページ全体より小さくトークン消費が少ない。2枚のままでは pixel-native の利点が出ない |
| Modal のレイアウト | タブではなく2行 | どちらの索引で比較しているかを常時可視化するため |
| 比較専用UI | 作らない | 設定切替+同じ質問の再送で足りる。YAGNI |
| LoRA アダプタ | 適用しない | Wikipedia スクリーンショット特化でありドメインが異なる。素の効果を測ってから判断 |

## 14. 完了条件

1. 設定を変更しない状態で、Stage 3 と同一の検索・生成結果が得られる(回帰なし)
2. `index_unit` / `search_strategy` の全6組み合わせが、設定切替のみで動作する(索引再構築を要求しない)
3. ページ索引とタイル索引を独立に構築・削除でき、Modal で両方の状態が同時に見える
4. `pixel_native` × vision 非対応モデルが明示エラーになる
5. §8.2 の CUDA 実機ゲートを通過する、または §8.4 の縮退着地が spec の想定どおりに機能する
6. UI 変更が evaluator 実機スクリーンショット検証で PASS する
