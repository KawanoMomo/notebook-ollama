#!/usr/bin/env bash
set -euo pipefail
PORT="${1:-8765}"
export NOTEBOOK_OLLAMA_DATA_DIR="${HOME}/.notebook-ollama"
uv run uvicorn apps.api.main:app --reload --host 127.0.0.1 --port "$PORT"
