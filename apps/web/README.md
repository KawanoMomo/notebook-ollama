# Notebook Ollama Web

SvelteKit frontend for Notebook Ollama. Consumes the REST + SSE API from the Python backend.

## Quickstart

1. Start the backend (in project root):
   ```
   uv run uvicorn apps.api.main:app --port 8765
   ```
2. Install web deps and start the dev server:
   ```
   cd apps/web
   npm install
   npm run dev
   ```
3. Open http://localhost:5173.

## Test

- `npm run check` — TypeScript / svelte-check
- `npm run test:unit` — unit tests (vitest)
- `npm run test:e2e` — Playwright (backend must be running on :8765)

## Build

```
npm run build
```

Outputs static assets to `dist/`, which can be served by FastAPI in production.
