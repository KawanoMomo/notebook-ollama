param([int]$Port = 8765)
$env:NOTEBOOK_OLLAMA_DATA_DIR = (Join-Path $env:USERPROFILE ".notebook-ollama")
# --no-sync: skip uv's implicit resolve+sync check on every invocation
# (faster, deterministic). Run `uv sync` / `uv sync --extra recording` /
# `uv sync --all-extras` yourself once; this script only ever reads the venv.
# NOTE: a bare `uv sync` (no --extra flag) run again later will silently
# strip any extra you previously added - see README recording-support section.
uv run --no-sync uvicorn apps.api.main:app --reload --host 127.0.0.1 --port $Port
