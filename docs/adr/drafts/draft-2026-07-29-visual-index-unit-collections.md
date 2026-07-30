---
type: adr-draft
title: 視覚索引の単位はコレクション分離(payloadフィルタでなく)とする
summary: "視覚索引の単位(ページ/タイル)を単一コレクションのpayloadフィルタで分けず、単位ごとに別コレクション(pages_visual/tiles_visual)を持ち同時保持する設計判断。"
aliases:
  - 視覚索引単位コレクション分離
status: proposed
date: 2026-07-30
project: NotebookOllama
area: retrieval
category: アーキテクチャ/データモデル
tags:
  - adr
  - draft
related:
  - "[[2026-07-29-pixelrag-tile-index-design]]"
  - "[[draft-2026-07-20-visual-index-qdrant-rrf]]"
---

# ADR-draft: 視覚索引の単位はコレクション分離(payloadフィルタでなく)とする

- **ステータス**: 提案(ドラフト・未採番)
- **カテゴリ**: アーキテクチャ/データモデル
- **日付**: 2026-07-30
- **出典**: PixelRAG式タイル索引と検索戦略の選択 `docs/specs/2026-07-29-pixelrag-tile-index-design.md` §5

## コンテキスト

Stage 4 で視覚索引の単位を `page`(1ページ1ベクトル、Stage 3 既存)と `tile`(ページをタイル分割して各タイルを1ベクトル、PixelRAG式)の2種類に増やす。両方を同時保持し、設定切替のみで(索引再構築なしに)行き来できることが要件(spec §14-2)。

## 検討した選択肢

### A) 単位ごとに別コレクション(`pages_visual` / `tiles_visual`)

- メリット: 単位ごとの独立した削除・再構築が素直にできる(Qdrantの `delete_collection` 一発)。構築状態(`visual_index_meta`)も単位ごとの行になり、テーブルの意味と実データの整合が取れる。設定切替に再構築が不要(既存コレクションをそのまま検索対象に切り替えるだけ)
- デメリット: Qdrantクライアントは既存 `VectorStore.client` を共有する必要があり(ローカルモードの1パス1クライアント制約)、コレクションが増えるほど共有クライアントの管理箇所が増える

### B) 単一コレクション + `unit` payload フィルタ

- メリット: コレクション数が増えない
- デメリット: 単位ごとの `drop`(削除)ができない(フィルタ削除は残存データのインデックス最適化を要する場合がある)。構築状態管理の複雑さが「PKで区別されたテーブル行」から「payload条件で絞ったクエリ」に移るだけで、根本的な解決にならない

## 決定

A を採用する。`core/storage/visual_store.py` の `VisualPageStore` を、コレクション名と単位を受け取る `VisualUnitStore` に一般化し、`pages_visual`(unit=`page`)と `tiles_visual`(unit=`tile`)の2インスタンスを構築する。`visual_index_meta` / `visual_index_sources` の主キーも `(notebook_id, unit)` / `(source_id, unit)` の複合キーに変更する。

SQLite は PRIMARY KEY の変更をサポートしないため、マイグレーション(`run_visual_index_unit_migration`)は「新テーブル作成 → 既存行を `unit='page'` として INSERT SELECT → 旧テーブル DROP → RENAME」の手順を取る。`conn.in_transaction` を見て、呼び出し元が既にトランザクション中でなければ `BEGIN IMMEDIATE` で自前トランザクションを張り、原子性を確保する。既に `unit` 列があれば何もしない(冪等)。

point ID のシード文字列は単位ごとに変える(`visualpage:{sid}:{page}` / `visualtile:{sid}:{page}:{tile_index}`)が、**`unit="page"` の書式は Stage 3 と1バイトも変えていない**。

## 結果

(2026-07-30 実装・実機検証済み)

- 決定どおり実装。このリポジトリ**初のテーブル再作成マイグレーション**となった。以降の PK 変更はこの型(新テーブル→INSERT SELECT→DROP→RENAME、`in_transaction` チェックによる原子性確保)を踏襲する
- **`unit="page"` の point ID シード文字列を Stage 3 と1バイトも変えなかったため、既に構築済みの `pages_visual` は再構築不要**だった。契約テスト `tests/integration/test_visual_store.py::test_page_point_id_is_unchanged_from_stage3` で固定(uuid5のnamespace・シード文字列とも既存実装から再計算した値と照合)
- コントローラ独立検証: tile と page が独立共存し `get_meta` / `list_indexed_source_ids` で読み分け可能。tile データが入った実DBに再 `migrate()` してもtile行が破壊されない(冪等性の実地確認)

## 教訓

- PKを変更できないDBでのスキーマ拡張は、後方互換の再構築コストをゼロにする余地がないか(point ID書式のような「実データに触れない部分」の互換維持)を先に検討する価値がある。今回はそこを死守できたことで実装完了直後から既存ユーザーの索引が無効化されずに済んだ
- テーブル再作成マイグレーションは原子性(全体が失敗したら全体をロールバック)を自前で担保する必要がある。`conn.in_transaction` で呼び出し元のトランザクション文脈を尊重しつつ、必要なら `BEGIN IMMEDIATE` で書き込みロックを早期に取得する設計は、以降の同種マイグレーションのテンプレートにできる
