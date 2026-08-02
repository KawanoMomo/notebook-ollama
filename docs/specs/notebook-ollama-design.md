---
type: spec
title: Notebook Ollama — 設計仕様書(基盤)
summary: "ローカルNotebookLMクローンの基盤設計。Ollama+Qdrant+SQLiteでノートブック単位RAG、MCP公開。"
aliases:
  - 基盤設計
  - Notebook Ollama 設計
status: approved
date: 2026-05-19
project: NotebookOllama
area: foundation
tags:
  - spec
note: 本文表記は「実装プラン待ち」だが実装済みのため approved に補正
code:
  - apps/api/routers
  - core/generation
  - core/ingestion/parsers
  - core/mcp/tools
  - core/retrieval
  - core/storage
---

# Notebook Ollama — 設計仕様書

- **作成日**: 2026-05-19
- **作成者**: Kawano Momo / Claude (brainstorming session)
- **対象プロジェクト**: 新規 `10_NotebookOllama` (仮称)
- **ステータス**: ブレインストーミング完了、実装プラン待ち

## 1. 概要

ローカルで動作する NotebookLM ライクなパーソナルナレッジベース。Ollama をバックエンドとし、ノートブック単位で複数ソース (PDF/Markdown/Web/Office) を取り込んで引用付き Q&A を行う。あわせて MCP サーバを公開し、他の LLM クライアントからも RAG クエリを利用できるようにする。

### 1.1 ゴール

- 個人ナレッジ全般 (技術文書、書籍、Web 記事、メモ等) を一元化し、横断的な質問に引用付きで回答する。
- 検索・生成・引用整形のすべてをサーバ側 (Ollama) で完結させ、呼び出し元 LLM のリソースに依存しない MCP インタフェースを提供する。
- NotebookLM 並みのリッチ UI を提供する (複数ノートブック、ソース選択、引用ハイライト連動)。

### 1.2 非ゴール (MVP では実装しない)

- 要約 / FAQ / Study Guide / Briefing Doc の自動生成
- 音声オーバービュー (NotebookLM の podcast 機能)
- マルチユーザ / 認証・認可 / 同時編集
- OCR (画像 PDF や手書きのテキスト化)
- ノートブック横断検索

### 1.3 利用シナリオ

1. ユーザがブラウザで Notebook Ollama を開き、「組み込み」ノートブックに ARM Cortex-M4 のユーザガイド PDF をドラッグ&ドロップ。
2. 取り込み完了後、「Cortex-M4 の例外優先度は何段階？」と質問。
3. サーバが Qdrant で検索 → Ollama で回答生成 → 引用付き応答をストリーミング。
4. ユーザが引用バッジ [^1] をクリック → 右パネルに該当ページがハイライト表示。
5. 別マシン/別 LLM クライアントから MCP 経由で `ask` ツールを呼び、同じノートブックに対して質問できる。

## 2. アーキテクチャ

### 2.1 採用スタック

- **バックエンド**: Python 3.12 + FastAPI、`uv` でパッケージ管理
- **LLM 推論**: Ollama (localhost:11434)
- **埋め込みモデル**: `bge-m3` (日本語/英語両対応、1024次元)
- **ベクタストア**: Qdrant local mode (組み込み、Docker 不要)
- **メタデータ DB**: SQLite
- **フロントエンド**: SvelteKit (静的ビルド、FastAPI が配信)
- **MCP**: 同一 FastAPI プロセス内で HTTP/SSE エンドポイントとして公開

### 2.2 プロセス構成

単一 FastAPI プロセスで Web UI / REST API / MCP サーバを同居させる。重い処理は `ProcessPoolExecutor` で隔離。

```
notebook-ollama/
├─ apps/
│  ├─ api/                  # FastAPI: REST + SSE + 静的UI配信
│  │  ├─ routers/
│  │  │  ├─ notebooks.py
│  │  │  ├─ sources.py
│  │  │  ├─ chat.py         # SSE streaming
│  │  │  └─ mcp.py          # MCP over HTTP/SSE
│  │  └─ main.py
│  └─ web/                  # SvelteKit、ビルド成果物を apps/api 配下に配置
├─ core/                    # FastAPI 非依存のドメインロジック
│  ├─ ingestion/            # parsers, chunkers, pipeline
│  ├─ embedding/            # Ollama embed client
│  ├─ retrieval/            # vector search, budgeter
│  ├─ generation/           # Ollama chat client, citation parser
│  ├─ storage/              # SQLite + Qdrant アダプタ
│  └─ mcp/                  # MCP tool 実装
├─ tests/
└─ pyproject.toml
```

### 2.3 責務境界の原則

- `core/*` は FastAPI/SvelteKit を import しない。純粋なドメインロジックでテスト可能。
- `apps/api/routers/*` は薄く、入力検証と `core` 呼び出しのみ。
- MCP tools 実装と Web UI の検索ロジックは `core/retrieval` を共有 (検索ロジックは1系統)。
- ストレージ層は `core/storage` のインタフェースで隠蔽 → 後で Qdrant→pgvector に差し替え可能。

### 2.4 プロセス内ジョブ

- 取り込みは FastAPI の `BackgroundTasks` + asyncio キュー。
- PDF パース・埋め込み生成等の重い処理は `concurrent.futures.ProcessPoolExecutor` で別プロセスに隔離。
- 進捗は SQLite に書き出し、UI は SSE 経由で受信。

### 2.5 Ollama リソースの共有方針

Web UI のチャット、MCP の `ask`、取り込み時の埋め込み生成はすべて同じローカル Ollama を共有する。これらの競合を避けるため、Ollama 呼び出しを抽象化した `OllamaGateway` を `core/generation/` に置き、グローバルに 1 つだけ存在させる:

- **チャット系 (`generate`)**: 同時実行 1。Web UI と MCP の両方ともこのゲートを通る。先着順 FIFO キューで待たせる (タイムアウト 60 秒、超過時は明示エラー)。
- **埋め込み系 (`embed`)**: 同時実行 1。チャット系とは別キュー (埋め込みはチャットをブロックしない)。
- ゲート内で同時実行数を上書き可能 (将来 GPU 余裕がある場合のため)。

UI 側は `[送信]` ボタン disable で重複送信を抑止する一方、サーバ側はこのゲートで最終的な競合制御を行う。

## 3. データモデル

### 3.1 SQLite スキーマ

```sql
notebooks (
  id           TEXT PRIMARY KEY,    -- ULID
  name         TEXT NOT NULL,
  description  TEXT,
  default_model TEXT,               -- このノートブック既定の Ollama モデル
  created_at   TIMESTAMP,
  updated_at   TIMESTAMP
)

sources (
  id           TEXT PRIMARY KEY,
  notebook_id  TEXT REFERENCES notebooks(id) ON DELETE CASCADE,
  kind         TEXT,                -- 'pdf'|'markdown'|'web'|'docx'|'pptx'|'xlsx'|'txt'
  title        TEXT,
  origin       TEXT,                -- 元ファイルパス or URL
  content_hash TEXT,                -- SHA-256
  status       TEXT,                -- 'pending'|'parsing'|'chunking'|'embedding'|'ready'|'error'
  error_msg    TEXT,
  bytes        INTEGER,
  page_count   INTEGER,
  chunk_count  INTEGER,
  created_at   TIMESTAMP,
  updated_at   TIMESTAMP,
  UNIQUE(notebook_id, content_hash)
)

chunks (
  id           TEXT PRIMARY KEY,    -- Qdrant point ID と一致
  source_id    TEXT REFERENCES sources(id) ON DELETE CASCADE,
  notebook_id  TEXT,                -- denormalized
  ord          INTEGER,
  page         INTEGER,             -- NULL 可
  heading_path TEXT,                -- "第3章 > 3.2 …" の整形済み
  text         TEXT NOT NULL,
  token_count  INTEGER
)

conversations (
  id           TEXT PRIMARY KEY,
  notebook_id  TEXT REFERENCES notebooks(id) ON DELETE CASCADE,
  title        TEXT,
  created_at   TIMESTAMP,
  updated_at   TIMESTAMP
)

messages (
  id              TEXT PRIMARY KEY,
  conversation_id TEXT REFERENCES conversations(id) ON DELETE CASCADE,
  role            TEXT,             -- 'user'|'assistant'
  content         TEXT,
  citations       TEXT,             -- JSON
  model           TEXT,             -- assistant のみ
  created_at      TIMESTAMP
)
```

### 3.2 Qdrant コレクション

- コレクション名: `chunks` (単一)
- ベクタ次元: 1024 (`bge-m3`)
- ペイロード: `{notebook_id, source_id, source_kind, page, heading_path, ord}`
- 検索時は `notebook_id` フィルタを必須適用 → ノートブック間の分離を保証。

### 3.3 保存場所

- ベースディレクトリ: `~/.notebook-ollama/`
- `metadata.db` (SQLite)
- `qdrant/` (Qdrant local mode のデータ)
- `sources/<source_id>/...` (原本ファイルを保持、再パース用)
- `logs/app.log` (rotate)
- `mcp.token` (MCP 認証トークン)
- `config.yaml` (グローバル設定)

### 3.4 設計判断

| 判断 | 理由 |
|---|---|
| chunks を SQLite と Qdrant に二重持ち | Qdrant は検索特化。「ソース全文プレビュー」「引用ハイライト」は SQLite で JOIN した方が速い |
| ULID 採用 | ソート可能・URL セーフ |
| `content_hash` で重複検知 | 同一 PDF を 2 回投げても再埋め込みしない |
| 会話履歴は notebook 紐付け | ノートブック間でチャット履歴を完全分離 |
| 原本ファイル保持 | 再パース・再チャンク化・将来の OCR 対応に備える |

## 4. 取り込みパイプライン

### 4.1 フロー

```
[Upload/URL] → 1.受信 → 2.重複検知 → 3.パース → 4.チャンク化 → 5.埋め込み → 6.Qdrant投入 → ready
                          ↓ (hit)
                       skip & alias
```

各ステージで例外発生時は `sources.status='error'` とし、`error_msg` を記録。UI から `[再試行]` で同じ source_id を最後の成功ステージから再開。

### 4.2 ステージ詳細

**1. 受信**
- ファイル: `POST /api/notebooks/{id}/sources` (multipart)
- URL: `POST /api/notebooks/{id}/sources/url`
- `sources` レコードを `status='pending'` で即作成し ID を返却。実処理は `BackgroundTasks`。

**2. 重複検知**
- バイナリは SHA-256 → `(notebook_id, content_hash)` UNIQUE 制約で弾く。
- URL 系は HEAD + ETag、なければ取得後の本文ハッシュで判定。

**3. パース**

| kind | ライブラリ | 抽出単位 |
|---|---|---|
| pdf | PyMuPDF (`pymupdf`) | page 単位、画像除外 |
| markdown | `markdown-it-py` | heading ツリー保持 |
| web | `trafilatura` | title + 本文 |
| docx | `python-docx` | paragraph + heading |
| pptx | `python-pptx` | slide 単位 + speaker notes |
| xlsx | `openpyxl` | sheet 単位 (CSV 化) |
| txt | 直接 | そのまま |

各 parser は `ParsedDocument` (= `list[ParsedSection]`) を返す。`ParsedSection` は `text, page, heading_path, ord` を持つ。

**4. チャンク化**
- 戦略: heading 境界を優先、サイズで微調整。
- 目標サイズ: 400–800 トークン (`tiktoken` cl100k_base で計測、日本語近似)
- オーバーラップなし (引用の明瞭さを優先)
- `heading_path` `page` は親セクションから継承。

**5. 埋め込み生成**
- `bge-m3` を Ollama 経由 (`POST /api/embeddings`)
- バッチ単位: 32 chunk
- リトライ: tenacity 3 回、exponential backoff

**6. Qdrant 投入**
- バッチ upsert
- 完了で `sources.status='ready'`、`chunk_count` 更新。

### 4.3 進捗通知

- `sources.status` 変更時に SSE `/api/notebooks/{id}/events` でプッシュ。
- UI のソースカードがリアルタイムで状態遷移を表示。

## 5. Q&A (RAG) パイプライン

### 5.1 フロー

```
質問 → embed → Qdrant 検索 (filter: notebook_id, top_k=20)
     → Top-k 絞り込み (k=8) → コンテキスト構築
     → Ollama chat (streaming) → 引用パース → SSE で UI へ → messages 保存
```

### 5.2 プロンプト

System プロンプト (固定):
```
あなたはユーザのノートブックに含まれるソースのみに基づいて回答するアシスタントです。
以下のルールに従ってください:
1. 提供された <sources> 内の情報のみを根拠に回答する。一般知識での補完は禁止。
2. 各主張の末尾に [^n] 形式で引用番号を付ける。
3. 引用できる情報がなければ「ノートブック内に該当情報がありません」と回答する。
4. 推測や憶測は明示的に区別する。
5. 回答は日本語で、簡潔かつ構造化 (必要に応じて箇条書き・表) で出力する。
```

User プロンプト:
```
<sources>
<source id="1" title="..." page="42">... chunk text ...</source>
<source id="2" title="..." heading="3.2 ...">... chunk text ...</source>
</sources>

質問: <ユーザの質問>
```

### 5.3 引用パース

- 出力ストリームを `[^数字]` 正規表現で監視。
- 番号 → chunk_id マッピングを保持し、最終的に `citations` JSON を構築。
- UI 側で `[^1]` をクリック可能なバッジに置換、ホバーで chunk スニペット表示。

### 5.4 会話履歴の動的選択

固定ターン数ではなく **トークン予算で動的に決める**。

```
コンテキスト予算 = num_ctx * context_budget_ratio (default 0.8)

予算配分の優先順:
1. System プロンプト (固定 ~500 トークン)
2. 現在の質問 (動的に計測)
3. 取得チャンク (top_k=8、最大 ~3500 トークン)
4. 応答用に確保する出力枠 (response_budget_tokens, default 1024)
5. 残りを会話履歴に充当
   → 直近ターン (assistant+user ペア) から逆順に積み、超過直前で停止
```

実装メモ:
- num_ctx は Ollama `/api/show {model}` から取得しキャッシュ (モデル切替時に再取得)。
- 履歴ペアが 1 つも入らない場合は chunks を段階的に削減 (8→6→4→2)。
- 最低 `min_history_turns` ターン (default 1) は必ず残す方針。
- 切り捨て時は UI に小バッジで `過去N件の会話は省略されました` 表示。

### 5.5 ストリーミング

- エンドポイント: `POST /api/notebooks/{id}/conversations/{cid}/messages`
- レスポンス: `text/event-stream`
- イベント種別: `retrieval` (検索ヒット一覧)、`token` (生成トークン)、`citation` (引用バッジ確定)、`done`、`error`

### 5.6 設定可能なパラメータ

| key | default | 説明 |
|---|---|---|
| `context_budget_ratio` | 0.8 | num_ctx の何割を使うか |
| `response_budget_tokens` | 1024 | 応答用に確保するトークン |
| `retrieval_top_k` | 8 | プロンプトに詰める最終 chunk 数 |
| `retrieval_top_k_max` | 20 | ベクトル検索でフェッチする上限 |
| `min_history_turns` | 1 | 必ず残す履歴ターン数 |

## 6. MCP インタフェース

### 6.1 設計原則

1. **生成は必ずサーバ側 Ollama で行う**。MCP は完成された回答を返す。
2. 呼び出し元 LLM のリソース (context window, 生成トークン) を消費する前提を持たない。チャンクを返却して呼び出し元側で再生成させる用途は MCP の範囲外。
3. 返却ペイロードは内部 ID を含めず、人間可読の `location` 表記に統一。
4. 認証は汎用 Bearer Token (起動時に生成、`~/.notebook-ollama/mcp.token` に保存)。
5. 呼び出し元がモデルを選択する余地は残す (`list_models` + `ask` の `model` パラメータ)。

### 6.2 プロトコル

- MCP 仕様: `2024-11-05` 系の HTTP/SSE 準拠
- エンドポイント: `GET /mcp/sse`, `POST /mcp/messages`
- 認証必須: `Authorization: Bearer <token>`
- 同時実行制御: §2.5 の `OllamaGateway` 経由で Web UI と共有される FIFO キュー

### 6.3 公開ツール

```json
{
  "tools": [
    { "name": "list_notebooks", "description": "利用可能なノートブック一覧と概要" },
    { "name": "list_models",    "description": "サーバ側 Ollama の選択可能モデル一覧と各ノートブックの default_model" },
    {
      "name": "ask",
      "description": "指定ノートブックに対し RAG-QA を実行し、引用付きの完成回答を返す。検索・生成・引用整形まですべてサーバ側で完了。",
      "inputSchema": {
        "required": ["notebook_id", "question"],
        "properties": {
          "notebook_id": {"type": "string"},
          "question":    {"type": "string"},
          "model":       {"type": "string", "description": "省略時はノートブックの default_model"},
          "style":       {"type": "string", "enum": ["concise","detailed","bullet"], "default": "concise"}
        }
      }
    },
    {
      "name": "find_quotes",
      "description": "指定トピックに関連するソース原文の引用ブロックを返す (生成なし)。",
      "inputSchema": {
        "required": ["notebook_id", "query"],
        "properties": {
          "notebook_id": {"type": "string"},
          "query":       {"type": "string"},
          "max_quotes":  {"type": "integer", "default": 5, "maximum": 10}
        }
      }
    },
    {
      "name": "get_source_outline",
      "description": "ソースの構造 (タイトル/見出し/ページ数) を返す。本文は返さない。",
      "inputSchema": {
        "required": ["source_id"],
        "properties": {"source_id": {"type": "string"}}
      }
    }
  ]
}
```

### 6.4 返却スキーマ

`ask`:
```json
{
  "answer": "...本文 with [1][2] markers...",
  "citations": [
    {"n": 1, "source_title": "ARM Cortex-M4 User Guide", "location": "p.42, §3.2 Memory Map", "url_or_path": "..."}
  ],
  "model_used": "qwen2.5:14b"
}
```

`find_quotes`:
```json
{
  "quotes": [
    {"text": "原文引用テキスト (最大 ~400 トークン目安)", "source_title": "...", "location": "p.42, §3.2"}
  ]
}
```

`list_models`:
```json
{
  "models": [
    {"name": "qwen2.5:14b", "size_bytes": 8500000000, "context_window": 32768, "modified_at": "...", "recommended_for": ["general","japanese"]}
  ],
  "defaults_by_notebook": [
    {"notebook_id": "01HF...", "name": "組み込み", "default_model": "qwen2.5:14b"}
  ]
}
```

### 6.5 モデル選択の挙動

- `ask` に `model` 指定 → そのモデルで生成。Ollama 未インストール時は 404 系エラーを返す。
- 省略時 → ノートブックの `default_model`。
- どちらも未設定 → グローバル設定の `default_model`。

### 6.6 ストリーミングについて

- `ask` は Ollama 生成中に `notifications/progress` を送る程度に留め、最終結果は単一レスポンス。
- トークン単位の中継表示は Web UI の責務 (MCP では扱わない)。

## 7. UI 構成

### 7.1 画面

1. **ホーム** (`/`) — ノートブック一覧、新規作成、各ノートブックのカード (ソース数 / 既定モデル / 更新時刻)
2. **ノートブック詳細** (`/notebooks/{id}`) — 3カラムレイアウト
3. **ソース追加モーダル** — ファイル選択 / URL 入力、複数同時アップロード対応
4. **設定** (`/settings`) — Ollama 接続、生成パラメータ、検索パラメータ、MCP 状態、ストレージ統計

### 7.2 ノートブック詳細 (メイン作業画面)

- **左サイドバー (Sources)**: チェックボックスでクエリ対象を絞り込み、ステータス色分け、`+` で追加、`[再試行]` ボタン (エラー時)
- **中央 (Conversation)**: Markdown レンダリング、引用バッジクリックで右パネル連動、ストリーミング表示、入力下に「履歴何往復含まれるか」のヒント
- **右パネル (Source Viewer)**: 折り畳み可、heading_path ツリー + ページ送り、引用 chunk を黄色ハイライト

PDF は MVP では抽出テキスト表示のみ (画像レンダリングはしない)。

### 7.3 ショートカット

| キー | 動作 |
|---|---|
| `Cmd/Ctrl+K` | Notebook switcher |
| `Cmd/Ctrl+/` | チャット入力にフォーカス |
| `Cmd/Ctrl+B` | 右パネル開閉 |
| `Cmd/Ctrl+Enter` | 送信 |
| `Esc` | モーダル/パネル閉じる |
| `↑` (チャット空時) | 直前の質問を再入力 |

### 7.4 状態管理 (SvelteKit stores)

- `notebookStore` — 一覧、CRUD
- `currentNotebookStore` — sources, selected_source_ids
- `conversationStore` — messages, streamingMessageId
- `eventStore` — SSE 接続を一元化 (取り込み進捗 + チャットストリーム)
- `settingsStore` — グローバル設定

## 8. エラー処理

### 8.1 分類

| カテゴリ | 例 | UI 挙動 | サーバ挙動 |
|---|---|---|---|
| 入力検証 | 空質問、未対応拡張子 | インライン赤字 | 400 |
| 取り込み失敗 | PDF パース失敗、URL 取得失敗 | ソースカード `error` 状態、`[再試行]` | `sources.status='error'`、再試行は最後の成功ステージから |
| Ollama 接続失敗 | サーバダウン、モデル未 pull | グローバルバナー | 503、ヘルスチェックで死活監視 |
| モデルロード失敗 | OOM、未 pull | チャットメッセージとして表示 | Ollama 4xx/5xx を整形 |
| context window 超過 | プロンプト長 > num_ctx | チャットで通知、削減提案 | §5.4 の段階的削減で吸収、それでも溢れたら明示エラー |
| Qdrant 接続失敗 | ストレージ破損 | グローバルバナー | 起動時 ping、失敗で起動拒否 |
| MCP 認証失敗 | トークン不一致 | (クライアント側 UI) | 401 |
| 同時実行制限 | Ollama 同時呼び出し | UI で送信 disable + `処理中...` | 内部キュー (429 は返さない) |

### 8.2 エラーレスポンス統一スキーマ

```json
{
  "error": {
    "code": "ollama.unreachable",
    "message": "Ollama に接続できません",
    "detail": "connection refused at http://localhost:11434",
    "remediation": "Settings から接続を確認してください"
  }
}
```

`code` はドット区切り名前空間 (`ingestion.parse_failed`, `retrieval.no_results`, `generation.context_overflow`, `mcp.unauthorized` 等)。UI は `code` で分岐表示。

### 8.3 ロギング

- 構造化ログ (`structlog` + JSON Lines)
- 出力先: `~/.notebook-ollama/logs/app.log` (rotate 10MB × 5)
- DEBUG 以上で本文を出力、INFO 以下では本文を出さない (PII 配慮)
- リクエスト相関 ID (`X-Request-ID`) を全ログ行に付与

### 8.4 観測性 (MVP 最小)

- `/api/health` — Ollama, Qdrant, SQLite の死活と `version`
- `/api/stats` — ノートブック数、ソース数、合計 chunk 数、ストレージ使用量
- 設定画面の Storage タブから統計表示

## 9. テスト戦略

### 9.1 テストレベル

| レベル | フレームワーク | 対象 |
|---|---|---|
| ユニット | pytest | `core/*` 各モジュール |
| 統合 (Ollama 不要) | pytest + httpx.AsyncClient | FastAPI ルーター、Qdrant local mode |
| 統合 (Ollama 要) | pytest, mark `ollama` | 実 Ollama 接続を通した Q&A |
| MCP | pytest + MCP test client | tools/resources の往復 |
| E2E (UI) | Playwright (Python) | 主要ユーザフロー |
| ビジュアル回帰 | Playwright screenshot | 主要画面のスナップショット |

### 9.2 ユニットテストの優先対象

- `core/ingestion/parsers/*` — 各フォーマットのゴールデンファイル比較
- `core/ingestion/chunker` — 境界条件 (短文、長文、heading 多階層、空セクション)
- `core/retrieval/budgeter` — §5.4 のトークン予算ロジック (履歴ターン数の動的選択)
- `core/generation/citation_parser` — `[^n]` 検出、不正パターン、ネスト
- `core/mcp/tools/*` — 各 tool の入出力スキーマ準拠

### 9.3 統合テストのケース

- ノートブック作成 → ソース追加 (MD) → 検索 → Q&A → 引用整合 のスループット
- 重複ソース投入で 2 回目 skip
- 取り込み失敗 → 再試行
- 同時 2 クエリのキュー直列化

### 9.4 E2E ゴールデンパス (Playwright)

1. ホームで Notebook 作成 → 詳細画面に遷移
2. PDF をドラッグ&ドロップ → `ready` まで遷移を観測
3. 質問を入力 → ストリーミング受信 → 引用バッジ表示
4. 引用クリック → 右パネルが該当箇所をハイライト
5. モデル切替 → 次の質問で `model_used` が変わる

### 9.5 ビジュアル回帰 (CLAUDE.md 準拠)

- GUI 変更を含む PR は必ずスクリーンショット差分を取得
- ベースライン画像: `tests/visual/baselines/`
- `evaluator` エージェントと Playwright MCP 経由の検証フローを連携

### 9.6 TDD 規律

- 新機能は failing test 先行 (superpowers:test-driven-development)
- バグ修正は再現テストを先に書いてから修正

### 9.7 カバレッジ目標

- `core/*` 80% 以上、`apps/api/*` 60% 以上 (router は薄いため)
- 当初は閾値を緩めにスタート、段階的に引き上げ

## 10. 設定ファイル例 (`~/.notebook-ollama/config.yaml`)

```yaml
ollama:
  endpoint: http://localhost:11434
  default_model: qwen2.5:14b
  embedding_model: bge-m3

generation:
  context_budget_ratio: 0.8
  response_budget_tokens: 1024

retrieval:
  top_k: 8
  top_k_max: 20
  min_history_turns: 1

server:
  host: 127.0.0.1
  port: 8765

mcp:
  enabled: true
  # token は起動時に自動生成して mcp.token に保存
```

## 11. 用語

| 用語 | 定義 |
|---|---|
| ノートブック (Notebook) | 関連ソースをまとめた論理単位。検索とチャットのスコープ |
| ソース (Source) | 取り込まれた個別ファイルや URL |
| チャンク (Chunk) | ソースを検索単位に分割したテキスト片 + 埋め込みベクトル |
| 引用 (Citation) | 回答中の `[^n]` バッジ。chunk への参照 |
| `num_ctx` | Ollama モデルのコンテキストウィンドウ長 |
