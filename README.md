# Notebook Ollama

Local NotebookLM-like personal knowledge base. Ollama-backed RAG with MCP server exposure.

See `../docs/superpowers/specs/2026-05-19-notebook-ollama-design.md` for the full design.

## License

Notebook Ollama itself is released under the [MIT License](./LICENSE).
Third-party dependency licenses are summarised in
[LICENSE-THIRDPARTY.md](./LICENSE-THIRDPARTY.md).

> **PDF ingestion is an opt-in extra**: it requires PyMuPDF (AGPL-3.0). Run
> `scripts/install-pdf-support.sh` (Linux / macOS) or
> `scripts/install-pdf-support.ps1` (Windows) and accept the AGPL terms before
> uploading PDF sources. Markdown / text / DOCX / PPTX / XLSX / web ingestion
> works without this extra.

## Quickstart

```bash
uv sync
uv run pytest
uv run uvicorn apps.api.main:app --reload --port 8765
```

To enable PDF ingestion:

```bash
# Linux / macOS
bash scripts/install-pdf-support.sh

# Windows PowerShell
pwsh scripts/install-pdf-support.ps1
```

## Frontend

See `apps/web/README.md`.

Production serves UI + API on one port:
```
cd apps/web && npm run build
cd ../..
uv run uvicorn apps.api.main:app --port 8765
```
Open http://localhost:8765.

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

## Deployment

### Prerequisites

| Requirement | Windows 11 | Linux | macOS |
|---|---|---|---|
| Ollama | [ollama.com/download](https://ollama.com/download) | same | same |
| Python 3.12 + `uv` | [docs.astral.sh/uv](https://docs.astral.sh/uv/getting-started/installation/) | same | same |
| Node.js 20+ + npm | [nodejs.org](https://nodejs.org/) | same | same |

Verify: `ollama --version`, `uv --version`, `node --version`

**Required Ollama models** (pull once before first run):

```
ollama pull bge-m3           # embedding — ~600 MB, no GPU required
ollama pull qwen2.5:14b      # LLM default — ~9 GB, needs ~10 GB VRAM
```

Alternative LLMs (less VRAM):

| Model | VRAM | Notes |
|---|---|---|
| `qwen2.5:7b` | ~6 GB | Faster, slightly less accurate |
| `qwen2.5:3b` | ~3 GB | CPU-friendly |
| `phi4:14b` | ~10 GB | English-strong alternative |

To use a different LLM, set `NOTEBOOK_OLLAMA_OLLAMA__DEFAULT_MODEL=qwen2.5:7b` or edit
`~/.notebook-ollama/config.json`.

### One-time setup

```powershell
uv sync
cd apps/web
npm install
npm run build
cd ../..
```

### Manual start (development or one-off)

```powershell
.\scripts\start.ps1
```

Add `-OpenBrowser` to open `http://localhost:8765/` automatically:

```powershell
.\scripts\start.ps1 -OpenBrowser
```

Use a custom port with `-Port`:

```powershell
.\scripts\start.ps1 -Port 9000
```

### Auto-start at logon (Windows)

Register the server as a Windows Scheduled Task that starts automatically when you log in:

```powershell
.\scripts\install-startup.ps1 -Run
```

- The server starts in the background at each logon
- View logs: `$env:USERPROFILE\.notebook-ollama\logs\server.log`
- To remove the auto-launch: `.\scripts\uninstall-startup.ps1`

### Stopping the server

**Foreground run:** Ctrl+C in the terminal.

**Background / scheduled task** — use the stop script (reads PID file):

```powershell
.\scripts\stop.ps1
```

Or via Task Scheduler GUI: open Task Scheduler, find `NotebookOllama`, click Stop.

The server records its PID to `$env:USERPROFILE\.notebook-ollama\server.pid` at startup
and deletes it on clean exit. `stop.ps1` uses this file to send the signal.

### Linux / macOS

```bash
chmod +x scripts/start.sh
./scripts/start.sh
./scripts/start.sh --background
./scripts/start.sh --port 9000 --open-browser
```

To run at startup on Linux, create a systemd user service pointing to `start.sh --background`
(template not included in this MVP):

```ini
# ~/.config/systemd/user/notebook-ollama.service
[Unit]
Description=Notebook Ollama server
After=network.target

[Service]
ExecStart=/bin/bash /path/to/scripts/start.sh --background
Restart=on-failure

[Install]
WantedBy=default.target
```

```bash
systemctl --user enable --now notebook-ollama
```

### Troubleshooting

- **`ollama: command not found`** — install Ollama from <https://ollama.com/download> and ensure
  it is on `PATH`. Restart your terminal after installation.
- **Port 8765 already in use** — pass `-Port <n>` to `start.ps1` (or `--port <n>` to `start.sh`).
- **Slow first response** — Ollama loads the model into VRAM on first inference; subsequent
  queries are fast.
- **MCP token location** — `$env:USERPROFILE\.notebook-ollama\mcp.token`. Copy this value for
  Claude Code or other MCP clients that require Bearer authentication.
- **Model warning at startup** — the start script warns if `bge-m3` or the default LLM is not
  found, but does **not** auto-pull (downloads can be several GB). Pull manually:
  ```
  ollama pull bge-m3
  ollama pull qwen2.5:14b
  ```
