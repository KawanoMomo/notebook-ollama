# Notebook Ollama

Local NotebookLM-like personal knowledge base. Ollama-backed RAG with MCP server exposure.

See `../docs/superpowers/specs/2026-05-19-notebook-ollama-design.md` for the full design.

## Quickstart

```bash
uv sync
uv run pytest
uv run uvicorn apps.api.main:app --reload --port 8765
```
