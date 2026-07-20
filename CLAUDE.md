# CLAUDE.md — Notebook Ollama

Local personal NotebookLM clone over Ollama with MCP exposure.

## Spec & Plan
- Spec: `./docs/specs/notebook-ollama-design.md`
- Plans (local-only, not tracked): `../docs/superpowers/plans/2026-05-19-notebook-ollama-backend.md` etc.

## Obsidian ナレッジ層 (LLM は vault を直接読む前提)

このリポジトリは Obsidian vault であり、LLM/エージェントが `docs/` の Markdown を
**ナレッジソースとして直接参照**する。設計・仕様・過去判断を調べるときは以下を起点にする。

### エントリポイント
1. `docs/設計資産MOC.md` — 索引ノート。ここから全設計書/ADRへ辿る(最初に読む)
2. `docs/設計資産.base` — frontmatter を絞り込む横断ビュー(設計書一覧/ステータス別/ADR台帳/領域別カード)
3. `docs/設計資産.canvas` — システム構成 → core モジュール → 設計書 → ADR の関係図

### frontmatter 規約 (必須)
`docs/specs` `docs/adr` 配下の .md には必ず frontmatter を付ける:
- `type` (spec | adr-draft) / `title` / `summary` (1行要約) / `status` / `date`
- `area` / `tags` / `related` ([[wikilink]]) / (ADRは) `category` / (推定時) `status_inferred: true`
- `status` 語彙: `draft` / `review` / `approved` / `planned` / `deferred` / `proposed`
- **`summary` を必ず書く**: frontmatter だけで文書の要旨が掴めること(全文を読まずに済む)
- 新規 spec/ADR を作ったら、frontmatter 付与 + MOC への追記をセットで行う(索引の鮮度 = 忘却の入口を塞ぐ)

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
