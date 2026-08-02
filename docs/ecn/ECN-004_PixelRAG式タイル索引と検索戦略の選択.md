---
type: ecn
title: PixelRAG式タイル索引と検索戦略の選択 (Stage 4)
summary: "ページをタイル分割して索引する方式を追加し、検索戦略(hybrid_rrf/visual_only/pixel_native)を設定から選べるようにした変更。既定値は現行挙動と完全一致させ、既存索引を無効化しない設計。"
status: applied
date: 2026-08-02
project: NotebookOllama
area: retrieval
tags:
  - ecn
related:
  - "[[2026-07-29-pixelrag-tile-index-design]]"
  - "[[014-visual-index-unit-collections]]"
  - "[[015-partial-success-per-unit]]"
  - "[[016-pixel-native-explicit-failure]]"
  - "[[ECN-003_視覚埋め込み第2インデックスとRRF融合]]"
  - "[[ECN-006_視覚索引の複合主キー移行]]"
---

# ECN-004: PixelRAG式タイル索引と検索戦略の選択 (Stage 4)

- **ステータス**: 適用済 (PR #27、2026-08-02 マージ)
- **種別**: 機能追加
- **対象コミット**: `0b4e3258..f39df568` (30コミット)
- **規模**: 60ファイル、+4,438 / -588
- **影響ファイル**: `core/visual/tiling.py` (新設), `core/storage/visual_store.py`,
  `core/storage/migrations.py`, `core/retrieval/search.py`, `core/generation/prompts.py`,
  `apps/api/routers/visual_index.py`, `apps/web/` (設定画面・Modal)

## コンテキスト

[PixelRAG](https://pixelrag.ai/) の「テキスト抽出を経ずピクセルのまま検索・回答する」
アプローチを、既存の視覚検索 (ECN-003) と**比較できる形**で試したいという要件。

制約は明確だった: **現行方式を壊さないこと**。Stage 3 の方式を残したまま、
設定から実験的方式に切り替えられる形にする。

## 対策

### 1. 索引単位はコレクション分離 (ADR-014)

`pages_visual` と `tiles_visual` を**別コレクション**として同時保持する。

**採用しなかった案**: 単一コレクション + `unit` payload フィルタ。
コレクション数は増えないが、単位ごとの削除・再構築が素直に書けない。

コレクション分離により**設定切替に再構築が不要**になった (既存コレクションを
検索対象に切り替えるだけ)。

### 2. ページの point ID を Stage 3 から変えない

```python
def _unit_point_id(unit, source_id, page, tile_index):
    if unit == "tile":
        return str(uuid.uuid5(_NS, f"visualtile:{source_id}:{page}:{tile_index}"))
    return str(uuid.uuid5(_NS, f"visualpage:{source_id}:{page}"))   # Stage 3 と同一
```

ページ側のシードを変えなかったため、**既存の `pages_visual` が無効化されない**
(再構築不要)。`test_page_point_id_is_unchanged_from_stage3` で固定した。

### 3. 検索戦略3分岐

| 戦略 | 挙動 |
|---|---|
| `hybrid_rrf` (既定) | テキスト検索 + 視覚検索を RRF 融合 (Stage 3 と同一) |
| `visual_only` | 視覚検索のみ |
| `pixel_native` | 視覚検索のみ + 画像だけを根拠に回答する専用プロンプト |

**既定値はすべて現行挙動と一致** (`index_unit="page"`, `search_strategy="hybrid_rrf"`)。
設定を触らないユーザーには何も変わらない。

### 4. pixel_native は黙って劣化させない (ADR-016)

根拠画像が1枚も用意できない場合、テキストにフォールバックせず**明示エラー**にする。
「ピクセルだけで答えた」という前提が崩れたまま回答が出ると、実験の意味が消えるため。
MCP (`ask`/`find_quotes`) も `pixel_native` を明示的に拒否する (`1a03b81`)。

### 5. 部分成功は単位ごとの独立性 (ADR-015)

ページ索引が失敗してもタイル索引の成否には影響しない。3値の結果を返す:

```python
if result.target_sources == 0:   outcome = "visual_index_noop"
elif result.indexed_pages == 0:  outcome = "visual_index_error"
else:                            outcome = "visual_index_complete"
```

## 結果

- 30コミット、`pytest -q` 1,559 passed / `npm run check` 0 errors /
  `npm run test:unit` 725 passed
- 実機検証 11/11 PASS (スクリーンショット4枚を視覚確認)
- **torch の CUDA 化** (ECN-005) を含み、視覚索引の構築が 147倍高速化した

### 効果測定 (2026-08-02、マージ後に実施)

167ページの実PDF・6問・4条件で retrieval を実測した結果、
**タイル分割の効果は確認できなかった**:

| 条件 | top-3 | top-5 |
|---|---|---|
| page / hybrid_rrf (既定) | 5/6 | 5/6 |
| tile / hybrid_rrf | 5/6 | 5/6 |
| page / visual_only | 4/6 | 6/6 |
| tile / visual_only | 5/6 | 6/6 |

- `hybrid_rrf` では **page と tile が6問すべてで順位完全一致**。テキスト側が常に
  視覚側より上位に来るため、索引単位の選択が最終結果に影響しなかった
- `visual_only` 内では 2問改善・1問悪化・3問同着で**一貫した改善にならなかった**
- タイル既定値 (rows=3 / cols=1 / overlap=0.1) は**現状維持**が結論
- 限界: 6問・1文書のみ。使ったPDFが機械翻訳版で図のラベルもテキスト抽出できたため、
  「図」の質問すらテキスト検索で解けていた

構築コストは **タイル化しても1.3倍**で済んだ (page 0.437秒/ページ、
tile 0.575秒/ページ相当 = 0.192秒/タイル)。埋め込み回数は3倍だが1枚が小さいため。

## 教訓

- **「既存を壊さず並べて比較できるようにする」という要件は、point ID の
  シード設計に落ちる。** ID が変われば既存索引は全部作り直しになる。
  互換性を保つ意図はテストで固定しておかないと、後のリファクタで簡単に壊れる
- **実験的機能は「黙って劣化しない」ことが実験の前提条件。** フォールバックは
  親切に見えて、測定対象を汚染する
- **効果測定は機能実装とは別に、実データで必ずやる。** 実装が正しく動くことと
  効果があることは別問題で、今回は「効果なし」が結論になった
- 測定の副産物として、**spec §8.3 の記述と実装の食い違い**が見つかった
  (`build_cooldown_seconds` が GPU でも無条件に効く)。長時間の実データ実行でしか
  出ない種類の問題
