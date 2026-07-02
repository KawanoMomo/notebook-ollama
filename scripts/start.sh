#!/usr/bin/env bash
# start.sh — Start Notebook Ollama server (production mode)
#
# Usage:
#   ./scripts/start.sh [--port PORT] [--background] [--open-browser]
#
# Options:
#   --port PORT       Port to listen on (default: 8765)
#   --background      Run uvicorn in background, redirect output to log file
#   --open-browser    Open browser after 2-second delay (uses xdg-open / open)
#
# Notes:
#   Large Ollama models (GPT-OSS:20B etc.) may need longer timeouts than the
#   600 s defaults. Either change them in Settings → Models / Ollama, or set:
#     export NOTEBOOK_OLLAMA_OLLAMA__REQUEST_TIMEOUT_SECONDS=1200
#     export NOTEBOOK_OLLAMA_OLLAMA__CHAT_READ_TIMEOUT_SECONDS=1200
#
set -euo pipefail

# ---------------------------------------------------------------------------
# 0. Paths
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
DATA_DIR="${HOME}/.notebook-ollama"
LOG_DIR="${DATA_DIR}/logs"
LOG_FILE="${LOG_DIR}/server.log"
PID_FILE="${DATA_DIR}/server.pid"
WEB_SRC_DIR="${PROJECT_ROOT}/apps/web/src"
WEB_DIST_IDX="${PROJECT_ROOT}/apps/web/dist/index.html"
WEB_DIR="${PROJECT_ROOT}/apps/web"

# Parse arguments
PORT=8765
BACKGROUND=false
OPEN_BROWSER=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --port)       PORT="$2";       shift 2 ;;
        --background) BACKGROUND=true; shift   ;;
        --open-browser) OPEN_BROWSER=true; shift ;;
        *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
done

# Ensure data + log dirs exist
mkdir -p "$LOG_DIR"

# ---------------------------------------------------------------------------
# 1. Check / start Ollama
# ---------------------------------------------------------------------------
test_ollama() {
    curl -sf --max-time 3 "http://localhost:11434/api/version" > /dev/null 2>&1
}

echo "[start] Checking Ollama..."
if ! test_ollama; then
    echo "[start] Ollama not responding. Attempting to start..."
    if command -v ollama &>/dev/null; then
        ollama serve > /dev/null 2>&1 &
    else
        echo "[start] ERROR: 'ollama' not found on PATH. Install from https://ollama.com/download" >&2
        exit 1
    fi

    # Wait up to 10 seconds
    waited=0
    while [ "$waited" -lt 10 ]; do
        sleep 1
        waited=$((waited + 1))
        if test_ollama; then break; fi
    done

    if ! test_ollama; then
        echo "[start] ERROR: Ollama did not come up within 10 seconds. Aborting." >&2
        exit 1
    fi
    echo "[start] Ollama started successfully."
else
    echo "[start] Ollama is reachable."
fi

# ---------------------------------------------------------------------------
# 2. Verify required models
# ---------------------------------------------------------------------------
echo "[start] Checking required models..."

# Read user-selected models from settings.json (the file the app actually
# writes). It is sparse, so missing keys fall back to the defaults below.
DEFAULT_MODEL="qwen2.5:14b"
EMBEDDING_MODEL="bge-m3"
SETTINGS_FILE="${DATA_DIR}/settings.json"
if [ -f "$SETTINGS_FILE" ]; then
    dm=$(python3 -c "
import json
try:
    cfg = json.load(open('${SETTINGS_FILE}'))
    print(cfg.get('ollama', {}).get('default_model', ''))
except Exception:
    pass
" 2>/dev/null || true)
    [ -n "$dm" ] && DEFAULT_MODEL="$dm"
    em=$(python3 -c "
import json
try:
    cfg = json.load(open('${SETTINGS_FILE}'))
    print(cfg.get('ollama', {}).get('embedding_model', ''))
except Exception:
    pass
" 2>/dev/null || true)
    [ -n "$em" ] && EMBEDDING_MODEL="$em"
fi

TAGS_JSON=$(curl -sf --max-time 10 "http://localhost:11434/api/tags" 2>/dev/null || true)
if [ -n "$TAGS_JSON" ]; then
    # Check embedding model. Ollama reports names as 'name:tag' (e.g.
    # 'bge-m3:latest'); when the wanted name has no tag, match on the base name.
    if ! echo "$TAGS_JSON" | python3 -c "
import json, sys
data = json.load(sys.stdin)
names = [m['name'] for m in data.get('models', [])]
w = '${EMBEDDING_MODEL}'
present = w in names or (':' not in w and any(n.split(':', 1)[0] == w for n in names))
sys.exit(0 if present else 1)
" 2>/dev/null; then
        echo "[start] WARNING: Embedding model '${EMBEDDING_MODEL}' not found."
        echo "        Run: ollama pull ${EMBEDDING_MODEL}"
    else
        echo "[start] Embedding model '${EMBEDDING_MODEL}' OK."
    fi

    # Check LLM (same base-name matching as the embedding model)
    if ! echo "$TAGS_JSON" | python3 -c "
import json, sys
data = json.load(sys.stdin)
names = [m['name'] for m in data.get('models', [])]
def present(w):
    return w in names or (':' not in w and any(n.split(':', 1)[0] == w for n in names))
candidates = ['${DEFAULT_MODEL}', 'qwen2.5:14b']
sys.exit(0 if any(present(c) for c in candidates) else 1)
" 2>/dev/null; then
        echo "[start] WARNING: LLM model '${DEFAULT_MODEL}' (or qwen2.5:14b) not found."
        echo "        Run: ollama pull ${DEFAULT_MODEL}"
        echo "        (Continuing — you may have configured a different model.)"
    else
        echo "[start] LLM model check OK."
    fi
else
    echo "[start] WARNING: Could not query Ollama model list."
fi

# ---------------------------------------------------------------------------
# 3. Build frontend if needed
# ---------------------------------------------------------------------------
echo "[start] Checking frontend build..."

needs_build=false
if [ ! -f "$WEB_DIST_IDX" ]; then
    echo "[start] dist/index.html not found — will build."
    needs_build=true
else
    # Check if any source file is newer than dist/index.html
    if find "$WEB_SRC_DIR" -newer "$WEB_DIST_IDX" -type f | grep -q .; then
        echo "[start] Source files newer than dist — will rebuild."
        needs_build=true
    fi
fi

if [ "$needs_build" = true ]; then
    if [ ! -d "${WEB_DIR}/node_modules" ]; then
        echo "[start] node_modules missing — running npm install..."
        (cd "$WEB_DIR" && npm install)
    fi
    echo "[start] Running npm run build..."
    (cd "$WEB_DIR" && npm run build)
    echo "[start] Frontend build complete."
else
    echo "[start] Frontend build is up to date."
fi

# ---------------------------------------------------------------------------
# 3b. Bootstrap the Python venv on first run only
# ---------------------------------------------------------------------------
# `uv run` (below) always uses --no-sync so this script never triggers an
# implicit resolve+sync on every single start (faster, deterministic: the
# venv is exactly what the user last explicitly `uv sync`'d, nothing more).
# That means uv will never auto-create the venv either, so do it here exactly
# once, the same way npm install/build are bootstrapped above for the
# frontend.
#
# IMPORTANT (the actual footgun this guards against): `uv run` by itself does
# NOT strip previously-installed optional extras (verified empirically). The
# command that DOES strip them is a **bare `uv sync`** run again later
# (e.g. re-following this README's own Quick Start after `git pull`, having
# already run `uv sync --extra recording` in an earlier session) - "no
# --extra flag" means "reset to the base dependency set", silently
# uninstalling soundfile/faster-whisper/etc. See README "録音サポート" section.
if [ ! -d "${PROJECT_ROOT}/.venv" ]; then
    echo "[start] .venv not found - running uv sync..."
    (cd "$PROJECT_ROOT" && uv sync)
    echo "[start] Dependencies installed. (Recording support is optional: uv sync --extra recording, or uv sync --all-extras for everything)"
fi

# ---------------------------------------------------------------------------
# 4. Start uvicorn
# ---------------------------------------------------------------------------
export NOTEBOOK_OLLAMA_DATA_DIR="$DATA_DIR"

cleanup() {
    if [ -f "$PID_FILE" ]; then
        rm -f "$PID_FILE"
    fi
}

if [ "$BACKGROUND" = true ]; then
    echo "[start] Starting server in background (log -> ${LOG_FILE})..."
    cd "$PROJECT_ROOT"
    # Single process: Qdrant local mode keeps an exclusive lock, so multiple
    # uvicorn workers cannot share the storage. Do NOT add --workers.
    # --no-sync: see the comment above the venv bootstrap check.
    uv run --no-sync uvicorn apps.api.main:app \
        --host 127.0.0.1 \
        --port "$PORT" \
        >> "$LOG_FILE" 2>&1 &
    SERVER_PID=$!
    echo "$SERVER_PID" > "$PID_FILE"
    echo "[start] Server PID ${SERVER_PID} written to ${PID_FILE}"
    echo "[start] Logs: ${LOG_FILE}"

    if [ "$OPEN_BROWSER" = true ]; then
        sleep 2
        if command -v xdg-open &>/dev/null; then
            xdg-open "http://localhost:${PORT}/" &>/dev/null &
        elif command -v open &>/dev/null; then
            open "http://localhost:${PORT}/"
        fi
    fi
else
    echo "[start] Starting server on http://127.0.0.1:${PORT}/ (foreground — Ctrl+C to stop)..."

    if [ "$OPEN_BROWSER" = true ]; then
        (
            sleep 2
            if command -v xdg-open &>/dev/null; then
                xdg-open "http://localhost:${PORT}/" &>/dev/null &
            elif command -v open &>/dev/null; then
                open "http://localhost:${PORT}/"
            fi
        ) &
    fi

    cd "$PROJECT_ROOT"
    trap cleanup EXIT

    uv run --no-sync uvicorn apps.api.main:app \
        --host 127.0.0.1 \
        --port "$PORT" &
    SERVER_PID=$!
    echo "$SERVER_PID" > "$PID_FILE"

    wait "$SERVER_PID" || true
    cleanup
fi
