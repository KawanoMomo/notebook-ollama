# Notebook Ollama

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](./LICENSE)
![Python](https://img.shields.io/badge/python-3.12+-blue.svg)
![Svelte](https://img.shields.io/badge/svelte-5-orange.svg)
![Ollama](https://img.shields.io/badge/llm-ollama-black.svg)

**ローカル完結**で動く NotebookLM ライクなパーソナルナレッジベース。  
Ollama を推論エンジン、Qdrant をベクトルストアとした **RAG** に加えて、**MCP サーバ**として他の LLM クライアントからも引用付き Q&A を呼べます。

![hero](./docs/screenshots/04-citation-viewer.png)

## 何ができるか

- **ソース取り込み**: PDF / Markdown / TXT / DOCX / PPTX / XLSX / Web URL を投入
- **引用付き Q&A**: 質問するとローカル LLM が回答 + 該当チャンクへのカード形式リンクを返す
- **3ペイン UI**: ソース一覧・チャット・ソースビューワを同時表示。引用カードクリックで該当ページの本文に即ジャンプ
- **OS 通知**: タブが非アクティブでも「回答完了」「取り込み完了」を OS 通知
- **進捗可視化**: 大型 PDF も `embedding (230/3629)` の形でリアルタイム進捗
- **MCP 公開**: Claude Desktop など他クライアントから `ask` / `find_quotes` / `list_models` などを呼べる
- **完全ローカル**: ノートデータ・ベクトル・モデル推論すべて手元で完結。クラウド依存なし

## スクリーンショット

### ノートブック一覧
![home](./docs/screenshots/01-home.png)

### 引用付きチャット（カード型 + クリックで該当チャンクへジャンプ）
![chat](./docs/screenshots/03-chat-with-citations.png)

### 出典カードから本文に飛ぶ
![viewer](./docs/screenshots/04-citation-viewer.png)

### ソース追加（モーダル）
![upload modal](./docs/screenshots/05-upload-modal.png)

### ドラッグ&ドロップ
パネルに直接ドロップで取り込み開始。  
![drag](./docs/screenshots/06-drag-overlay.png)

## アーキテクチャ

```
┌──────────────────────────────────────────────────────────────┐
│  Browser (SvelteKit + Svelte 5)   :5173 (dev) / :8765 (prod) │
└──────────────────────────────────┬───────────────────────────┘
                                   │ HTTP / SSE
┌──────────────────────────────────▼───────────────────────────┐
│  FastAPI  (apps/api)                                          │
│  ├─ /api/notebooks, /sources, /conversations, /messages …    │
│  ├─ /api/notebooks/{id}/events  (SSE: 進捗・状態遷移)        │
│  └─ /mcp/*  (MCP SSE server, Bearer token 認証)              │
└──────────────────────────────────┬───────────────────────────┘
                                   │
                ┌──────────────────┼──────────────────┐
                ▼                  ▼                  ▼
        ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
        │   SQLite     │  │   Qdrant     │  │   Ollama     │
        │  (metadata)  │  │  (vectors)   │  │  (LLM/Embed) │
        └──────────────┘  └──────────────┘  └──────────────┘
```

| レイヤ | 採用 |
|---|---|
| 推論 | Ollama (`qwen2.5:14b` など) |
| 埋め込み | Ollama `bge-m3` (1024次元) |
| ベクトル DB | Qdrant ローカルモード |
| メタデータ | SQLite |
| バックエンド | FastAPI (Python 3.12) |
| フロント | SvelteKit + Svelte 5 |
| MCP | Anthropic 公式 MCP SDK (`mcp[cli]`) |

詳細設計は [`docs/specs/notebook-ollama-design.md`](./docs/specs/notebook-ollama-design.md)。

## ライセンス

Notebook Ollama 本体は **MIT** で公開しています ([`LICENSE`](./LICENSE))。  
依存ライブラリのライセンスは [`LICENSE-THIRDPARTY.md`](./LICENSE-THIRDPARTY.md) を参照。

> **PDF 取り込みだけは opt-in 拡張**です。PDF パーサに使用する PyMuPDF は AGPL-3.0 のため、本体には同梱せず、利用者が同意付きスクリプトを実行したときのみ有効化します。  
> Markdown / TXT / DOCX / PPTX / XLSX / Web は本体だけで動きます。

## クイックスタート

### 1. 前提条件

| 必要なもの | Windows 11 | Linux | macOS |
|---|---|---|---|
| Ollama | [ollama.com/download](https://ollama.com/download) | 同左 | 同左 |
| Python 3.12 + `uv` | [docs.astral.sh/uv](https://docs.astral.sh/uv/getting-started/installation/) | 同左 | 同左 |
| Node.js 20+ | [nodejs.org](https://nodejs.org/) | 同左 | 同左 |

### 2. モデル取得 (初回のみ)

```bash
ollama pull qwen2.5:14b   # 約 9 GB
ollama pull bge-m3        # 約 1.2 GB
```

### 3. 起動

```bash
# 依存インストール
uv sync
cd apps/web && npm install && cd ../..

# API サーバ
uv run uvicorn apps.api.main:app --port 8765
# 別ターミナルで dev UI
cd apps/web && npm run dev   # http://localhost:5173
```

### 4. PDF サポート (任意)

```bash
# Linux / macOS
bash scripts/install-pdf-support.sh

# Windows PowerShell
pwsh scripts/install-pdf-support.ps1
```

AGPL-3.0 の同意プロンプトに `y` で答えると PyMuPDF が `uv sync --extra pdf` でインストールされます。

## 本番ビルド

```bash
cd apps/web && npm run build   # → apps/web/dist/
cd ../..
uv run uvicorn apps.api.main:app --port 8765
# UI + API を同じ :8765 で提供
```

## MCP サーバとして使う

起動時に `~/.notebook-ollama/mcp.token` が生成されます。Claude Desktop 等から:

```json
{
  "mcpServers": {
    "notebook-ollama": {
      "url": "http://localhost:8765/mcp/sse",
      "headers": { "Authorization": "Bearer <内容を貼り付け>" }
    }
  }
}
```

公開ツール: `ask` / `find_quotes` / `list_notebooks` / `list_models` / `get_source_outline`

## 開発

```bash
uv run pytest                 # ユニット + 統合 (Ollama 不要)
uv run pytest -m ollama       # Ollama 必要なテスト
cd apps/web && npm run check  # 型チェック
cd apps/web && npm run test:unit
```

レイアウト:

- `core/` — ドメインロジック (FastAPI 非依存)
- `apps/api/` — FastAPI ルータ / スキーマ
- `apps/web/` — SvelteKit フロント
- `tests/unit` `tests/integration` `tests/mcp` — テスト分離

## ライセンス

[MIT](./LICENSE) — Copyright (c) 2026 Kawano Momo
