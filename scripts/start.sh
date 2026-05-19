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

# Determine configured default_model from config.json if available
DEFAULT_MODEL="qwen2.5:14b"
CONFIG_FILE="${DATA_DIR}/config.json"
if [ -f "$CONFIG_FILE" ]; then
    parsed=$(python3 -c "
import json, sys
try:
    cfg = json.load(open('${CONFIG_FILE}'))
    print(cfg.get('ollama', {}).get('default_model', ''))
except Exception:
    pass
" 2>/dev/null || true)
    if [ -n "$parsed" ]; then
        DEFAULT_MODEL="$parsed"
    fi
fi

EMBEDDING_MODEL="bge-m3"

TAGS_JSON=$(curl -sf --max-time 10 "http://localhost:11434/api/tags" 2>/dev/null || true)
if [ -n "$TAGS_JSON" ]; then
    # Check embedding model
    if ! echo "$TAGS_JSON" | python3 -c "
import json, sys
data = json.load(sys.stdin)
names = [m['name'] for m in data.get('models', [])]
sys.exit(0 if '${EMBEDDING_MODEL}' in names else 1)
" 2>/dev/null; then
        echo "[start] WARNING: Embedding model '${EMBEDDING_MODEL}' not found."
        echo "        Run: ollama pull ${EMBEDDING_MODEL}"
    else
        echo "[start] Embedding model '${EMBEDDING_MODEL}' OK."
    fi

    # Check LLM
    if ! echo "$TAGS_JSON" | python3 -c "
import json, sys
data = json.load(sys.stdin)
names = [m['name'] for m in data.get('models', [])]
candidates = ['${DEFAULT_MODEL}', 'qwen2.5:14b']
sys.exit(0 if any(c in names for c in candidates) else 1)
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
    uv run uvicorn apps.api.main:app \
        --host 127.0.0.1 \
        --port "$PORT" \
        --workers 1 \
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

    uv run uvicorn apps.api.main:app \
        --host 127.0.0.1 \
        --port "$PORT" \
        --workers 1 &
    SERVER_PID=$!
    echo "$SERVER_PID" > "$PID_FILE"

    wait "$SERVER_PID" || true
    cleanup
fi
