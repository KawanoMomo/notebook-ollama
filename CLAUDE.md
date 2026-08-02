# CLAUDE.md — Notebook Ollama

Local personal NotebookLM clone over Ollama with MCP exposure.

## Spec & Plan
- Spec: `./docs/specs/notebook-ollama-design.md`
- Plans (local-only, not tracked): `../docs/superpowers/plans/2026-05-19-notebook-ollama-backend.md` etc.

## Obsidian ナレッジ層 (LLM は vault を直接読む前提)

このリポジトリは Obsidian vault であり、LLM/エージェントが `docs/` の Markdown を
**ナレッジソースとして直接参照**する。設計・仕様・過去判断を調べるときは以下を起点にする。

> [!important] 探索の原則
> **コード全体を Grep する前に、まず索引を引く。** どのコードがどの設計書に規定されて
> いるかは `docs/実装マップ.md` に永続化してある。Grep は「マップに載っていないとき」
> の最後の手段。同じ調査を毎回やり直さないための仕組み。

### 目的別ルーティング

| やりたいこと | 最初に開くもの |
|---|---|
| **既存コードを直す / 仕様の根拠を知る** | `docs/実装マップ.md` (コード → 設計書 逆引き) |
| **機能の全体像を知る** | `docs/設計資産MOC.md` (領域別の索引) |
| **一覧・絞り込み (status/area)** | `docs/設計資産.base` |
| **構成と依存の俯瞰** | `docs/設計資産.canvas` |
| **設計判断の理由を辿る** | 該当 spec の `related` → ADR ドラフト |
| **未実装かどうかの判別** | 実装マップの「コード未紐付けの設計書」節 |

### コード → 設計書 早見表 (詳細は `docs/実装マップ.md`)

| モジュール | 主に規定している設計書 |
|---|---|
| `core/recording` | 録音ソース / 録音命名 / ミュート・話者リネーム |
| `core/ingestion` | 基盤設計 / PDF表・図サイドカー(Stage 1) |
| `core/retrieval` | 基盤設計 / RAG運用UX改善 / 表・図Stage 1 / PixelRAG(Stage 4) |
| `core/generation` | 基盤設計 / RAG運用UX改善 / 表・図Stage 1 |
| `core/summary` | ソースガイド / 要約プロンプト改善 |
| `core/ollama` | モデル選択 / iGPU・NPU対応 / VLM図説明(Stage 2) |
| `core/accel` | iGPU・NPU / Ryzen AI 対応 |
| `core/storage` | 基盤設計ほか9本 (永続化は横断的) |
| `core/feedback_hub` `core/crash_reporter` | クラッシュレポート & フィードバックハブ |
| `core/dev_logs` | 開発者モード |
| `apps/web` | 各機能の UI 章 (実装マップで個別ファイル単位に引ける) |

### エントリポイント
1. `docs/実装マップ.md` — コード → 設計書の逆引き(**Grep の代替**。自動生成)
2. `docs/設計資産MOC.md` — 索引ノート。ここから全設計書/ADRへ辿る
3. `docs/設計資産.base` — frontmatter を絞り込む横断ビュー(設計書一覧/ステータス別/ADR台帳/領域別カード)
4. `docs/設計資産.canvas` — システム構成 → core モジュール → 設計書 → ADR の関係図

### frontmatter 規約 (必須)
`docs/specs` `docs/adr` 配下の .md には必ず frontmatter を付ける:
- `type` (spec | adr-draft) / `title` / `summary` (1行要約) / `status` / `date`
- `area` / `tags` / `related` ([[wikilink]]) / (ADRは) `category` / (推定時) `status_inferred: true`
- `status` 語彙: `draft` / `review` / `approved` / `planned` / `deferred` / `proposed`
- **`summary` を必ず書く**: frontmatter だけで文書の要旨が掴めること(全文を読まずに済む)
- `code` は手書きしない。**設計書の本文に実装ファイルのパスを書く**と
  `gen_code_map.py` が実在するパスだけを抽出して frontmatter に落とす
  (= 次回から Grep 不要になる。実装したらパスを本文に書く習慣をつける)

### 索引の再生成 (doc を追加・変更したら必ず実行)
```
uv run python scripts/gen_code_map.py       # 本文のパス → code: と docs/実装マップ.md
uv run python scripts/gen_design_canvas.py  # frontmatter → docs/設計資産.canvas
uv run python scripts/check_design_index.py # 索引の鮮度検査 (異常なら exit 1)
```
- `docs/実装マップ.md` と `docs/設計資産.canvas` は**自動生成物。手編集しない**
- `docs/設計資産.base` はフィルタ式のため再生成不要(frontmatter を付ければ自動で載る)
- `docs/設計資産MOC.md` は手書き。新規 spec/ADR を作ったら追記する
  (check スクリプトが掲載漏れを検出する)

### 参照ルール
- 特定機能を調べる → Base を `area` で絞る、または MOC の該当領域を開く
- 設計判断の理由を辿る → `related` の ADR を開く(上位 CLAUDE.md の ADR/ECN 参照ゲートと連動)
- NotebookOllama の MCP (`ask`/`find_quotes`) は「取り込んだノートブックのソース」が対象で、
  この `docs/` は対象外。`docs/` は vault の Markdown を直接読むこと

## Run
```
uv run --no-sync uvicorn apps.api.main:app --reload --port 8765
```
`--no-sync` matters: a bare `uv run` re-syncs the venv to the base lockfile
before every invocation, silently dropping any optional extra installed by
hand (`uv sync --extra recording`, `--extra pdf`). Run `uv sync` yourself once
(with whichever extras you want); this command never touches the venv after
that.

## Test
```
uv run pytest                  # default (skip ollama-marked)
uv run pytest -m ollama        # requires running Ollama
```

## Layout
- `core/` — pure domain logic (no FastAPI imports)
- `apps/api/` — FastAPI routers + schemas
- `tests/unit` — pure unit, no IO
- `tests/integration` — sqlite/qdrant local, fake ollama
- `tests/mcp` — MCP server contract

## Frontend

SvelteKit web UI in `apps/web/`. Dev: `cd apps/web && npm run dev` (proxies API to :8765).
Build: `npm run build` outputs to `apps/web/dist/`, served by FastAPI in production.
