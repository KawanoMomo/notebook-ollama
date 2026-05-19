# Notebook Ollama

Local NotebookLM-like personal knowledge base. Ollama-backed RAG with MCP server exposure.

See `../docs/superpowers/specs/2026-05-19-notebook-ollama-design.md` for the full design.

## Quickstart

```bash
uv sync
uv run pytest
uv run uvicorn apps.api.main:app --reload --port 8765
```

## Smoke Test

1. Start Ollama: `ollama serve`
2. Pull required models:
   ```
   ollama pull bge-m3
   ollama pull qwen2.5:14b
   ```
3. Start the backend:
   ```
   uv run uvicorn apps.api.main:app --port 8765
   ```
4. Create a notebook and upload a markdown file:
   ```
   curl -s -X POST http://localhost:8765/api/notebooks \
        -H "Content-Type: application/json" \
        -d '{"name":"smoke","default_model":"qwen2.5:14b"}'

   NB=$(curl -s http://localhost:8765/api/notebooks | python -c 'import sys,json;print(json.load(sys.stdin)[0]["id"])')

   echo "# Test\n\nHello world." > /tmp/a.md
   curl -s -F "file=@/tmp/a.md" http://localhost:8765/api/notebooks/$NB/sources
   ```
5. Ask via REST:
   ```
   CV=$(curl -s -X POST http://localhost:8765/api/notebooks/$NB/conversations | python -c 'import sys,json;print(json.load(sys.stdin)["id"])')
   curl -N -s -X POST http://localhost:8765/api/notebooks/$NB/conversations/$CV/messages \
        -H "Content-Type: application/json" \
        -d '{"content":"何が書かれていますか"}'
   ```
6. Ask via MCP:
   ```
   TOKEN=$(cat ~/.notebook-ollama/mcp.token)
   curl -s -X POST http://localhost:8765/mcp/messages \
        -H "Authorization: Bearer $TOKEN" \
        -H "Content-Type: application/json" \
        -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
   ```
   Expected: tools list includes `ask`, `find_quotes`, `list_notebooks`, `list_models`, `get_source_outline`.
