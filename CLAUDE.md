# CLAUDE.md — Notebook Ollama

Local personal NotebookLM clone over Ollama with MCP exposure.

## Spec & Plan
- Spec: `../docs/superpowers/specs/2026-05-19-notebook-ollama-design.md`
- Plan: `../docs/superpowers/plans/2026-05-19-notebook-ollama-backend.md`

## Run
```
uv run uvicorn apps.api.main:app --reload --port 8765
```

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
