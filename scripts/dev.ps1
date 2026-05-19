param([int]$Port = 8765)
$env:NOTEBOOK_OLLAMA_DATA_DIR = (Join-Path $env:USERPROFILE ".notebook-ollama")
uv run uvicorn apps.api.main:app --reload --host 127.0.0.1 --port $Port
