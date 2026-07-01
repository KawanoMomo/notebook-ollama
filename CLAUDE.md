# CLAUDE.md — Notebook Ollama

Local personal NotebookLM clone over Ollama with MCP exposure.

## Spec & Plan
- Spec: `./docs/specs/notebook-ollama-design.md`
- Plans (local-only, not tracked): `../docs/superpowers/plans/2026-05-19-notebook-ollama-backend.md` etc.

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
