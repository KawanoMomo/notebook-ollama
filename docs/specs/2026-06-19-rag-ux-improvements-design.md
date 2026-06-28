# RAG運用UX改善(群1) 設計仕様

> 対象: 録音→RAG機能の次フェーズ「群1(UX即効・低リスク)」。#4 設定戻る / #6 取得スコープ化 / #7 ソース全文ビュー / #5 録音再生成 / #8 チャット待機UX の5件。
> 群2(#2モデル選択 / #3保存先パス)・群3(#1アクセラレータ / #9リモート推論)は**本仕様の対象外**(別仕様で扱う)。

作成日: 2026-06-19 / ブランチ: 別途 `feature/rag-ux-improvements` を切って実装(master直接編集は禁止)。

## 1. 目的
録音→RAG機能の体感品質を、低リスクな範囲で底上げする。新規の重い依存やエンジン追加は行わず、既存の配線・コンポーネント・永続化パターンを再利用する。各機能は「設計→実装→**Playwright実機スクショ検証**」を個別に回す(GUI変更は自動テストGREENのみでのPASS禁止)。

## 2. 決定事項(確定)
| # | 機能 | 決定 |
|---|---|---|
| #4 | 設定の戻るボタン | 戻り先は**元の画面**(直前ルートを記憶、無ければ `/`)。設定見出し横に `ArrowLeft`+`goto` の戻る矢印(ノートブック詳細と同パターン)。 |
| #6 | 取得スコープ化 | `source_ids` allowlist を全層に配線。**未選択=全件**(現状維持)。選択は**リクエスト毎の揮発**(永続化しない)。**Webチャットのみ**(MCPツールは当面据置)。 |
| #7 | ソース全文ビュー | サイドバーのソース**クリックだけ**で右ビューアに全文表示。**文書=元ファイルを再パースして忠実表示**。**録音=生成済みトランスクリプト**(ord順、話者チップ+タイムコード、**共有プレーヤー1個+行クリックでシーク**)。 |
| #5 | 録音再生成 | 状態は **`ready` 維持**、サイドバーに**再生成ボタン**追加(録音 && (status=error または chunk_count=0))。**圧縮音源(.m4a/.opus)から再STT**(WAV削除済みのため唯一手段)。音源の無い録音は `has_audio` フラグで**ボタン非表示**。 |
| #8 | チャット待機UX | (a)待機スピナーを `streaming` 即時表示(「参照中…→生成中…」)。(b)**SSEハートビート**で実ストリーム死活検知+**Stopボタン**追加(`chat_stream` に読み取りタイムアウトも付与)。(c)送信ボタンは**空入力で通常表示**(押下は無反応)、トーンダウンは**返答待ち中のみ**。返答待ち中もテキストエリア編集可。 |

## 3. 機能別設計

### #4 設定の戻るボタン
- 現状: `apps/web/src/routes/settings/+page.svelte` に戻る導線なし(ブランドリンクで `/` に行くのみ)。保存はセクション毎に即時永続化済み(別途「適用」概念は不要)。
- 変更:
  - 設定ページ先頭の `<h1>設定</h1>` を `.topbar`(ノートブック詳細 `routes/notebooks/[id]/+page.svelte` L66-72 のCSS流用)で包み、`<button class="back" onclick={goBack} aria-label="戻る"><ArrowLeft size="16"/></button>` を置く。
  - 戻り先=元の画面: 設定遷移時に直近ルートを記録する(小さな nav 記憶 store、または `?from=<path>` クエリを `AppHeader` の歯車リンクに付与)。`goBack()` は `from ?? '/'` へ `goto`。リロード/直リンク時は `/`。
  - 未保存ドラフト(音声セクション)は警告せず離脱可(各セクションに `保存` があるため)。
- 検証: 設定を開く→戻る矢印→直前のノートブックに戻ることをスクショ確認。

### #6 取得スコープ化(チェック済みのみ検索)
- 現状: スコープ完全不在。`currentNotebookStore.selectedSourceIds` は `SourcesPanel` のチェックボックス表示にのみ使われ、検索に届かない。`VectorStore.search` の Qdrant フィルタは `notebook_id` のみ。
- 変更(下層→上層):
  - `core/storage/vector_store.py::VectorStore.search`: 引数に `source_ids: list[str] | None = None` を追加。非空なら `query_filter.must` に `qm.FieldCondition(key="source_id", match=qm.MatchAny(any=source_ids))` を追加(payload に `source_id` 既存、`delete_by_source` と同パターン)。
  - `core/retrieval/search.py::RetrievalService.search`: `source_ids` 引数追加→ `_vs.search` へ透過。
  - `core/generation/stream.py::GenerationService.run` + `_RetrievalLike` Protocol: `source_ids` 追加→ `retrieval.search` へ透過。
  - `apps/api/schemas/chat.py::MessageInput`: `source_ids: list[str] | None = None` を追加。
  - `apps/api/routers/chat.py::send_message`: body の `source_ids` を `ctx.generation.run` へ渡す。
  - フロント: `lib/api/chat.ts::sendMessage` の body に `source_ids` を含める。`lib/stores/conversation.svelte.ts::send` が `source_ids` を受け取り転送。`ChatPanel.svelte` 送信時に `currentNotebookStore.selectedSourceIds`(Set→配列)を渡す。
  - 既定: `source_ids` が空/未指定 = 全件(現状維持)。
  - MCP(`core/mcp/tools/ask.py`, `find_quotes.py`)は本仕様では据置(将来別途)。
- 検証: 2ソースのうち1つだけチェック→そのソースにしか無い内容を質問→引用がチェック済みソースのみから出ることを確認(チェック切替で結果が変わる)。

### #7 ソース全文ビュー
- 現状: ソース選択時(`selectedChunkId=null`)はヘッダのみ描画、本文は空。引用クリック時のみ単一チャンク表示。全チャンク/全文を返すHTTPエンドポイント無し。
- バックエンド:
  - 文書用(忠実): `GET /api/notebooks/{nb}/sources/{sid}/content` を新設。`src.kind` が文書系なら `sources_dir/<id><ext>` の元バイト列を `core/ingestion/parsers` で再パースし、忠実な本文(見出し/ページ構造付き)を返す。
  - 録音用(生成済み): 同エンドポイントで `src.kind=="recording"` なら `chunks` を `ORDER BY ord ASC` で返す(`core/storage/chunks_repo.py` に `list_chunks_for_source` を追加)。各要素 = {ord, text, start_ms, end_ms, speaker}。
  - レスポンスは `kind` 判別付き: 文書 `{kind:"document", sections:[...] }`、録音 `{kind:"recording", segments:[...] }`。
  - 注: パーサ再実行コストは表示毎に発生。重い文書はキャッシュ検討(初期は都度パースで可、計測して必要なら追加)。
- フロント(`SourceViewer.svelte`):
  - `resolvedSourceId` があり `selectedChunkId===null` のとき、`sourceDetailApi.getSourceContent(notebookId, sourceId)` を呼んで全文描画。引用クリックの単一チャンク経路は不変。
  - 文書: セクション順に本文表示(見出し/ページ)。
  - 録音: ord順トランスクリプトを「話者チップ+`mm:ss` タイムコード+本文」の行リストで表示。**ビューア上部に共有 `<audio>` プレーヤー1個**(channel別、`AudioCitationPlayer` を流用/一般化)、各行クリックでその `start_ms` にシーク。
  - `lib/api/source_outline.ts` に `getSourceContent` + 型追加。
- 検証: 文書ソースをクリック→右に忠実全文。録音ソースをクリック→トランスクリプト全文、行クリックで該当秒へシーク再生をスクショ確認。

### #5 録音再生成(再埋め込み)
- 現状: 0チャンクでも `status=ready, chunk_count=0` で終了(errorではない)。録音用retryエンドポイント無し(既存 `retry_source` は文書専用で `_EXT_BY_KIND` に recording 無し)。`Transcriber.transcribe` は PyAV デコードのため **.m4a/.opus/.mp3 も受理**可能(`wav_path` 名は誤称)。
- バックエンド:
  - 新規 `POST /api/notebooks/{nb}/recordings/{sid}/retry`(`recordings.py`)。`stop_recording` の dispatch を再利用:
    - `src.kind=="recording"` とノートブック所有を検証。
    - `audio.py::_resolve_audio_path` 相当でチャンネル別に圧縮音源 or wav を解決(`sources_dir/<id>/{mic,system}.{m4a,opus,mp3,wav}`)。両チャンネルとも音源が無ければ 422(`no audio to re-embed`)。
    - `delete_chunks_for_source` + `vector_store.delete_by_source` でクリア、`status=PARSING`、`background.add_task(ctx.recording_pipeline.run, ...)`(`_get_transcriber`/`_get_diarizer` と現行音声設定を流用)。
  - `Source` スキーマ(`apps/api/schemas/source.py` + `_to_schema`)に `has_audio: bool` を追加(`sources_dir/<id>/` にチャンネル音源が存在するか)。GET/list/該当APIで返す。
- フロント:
  - `SourceCard.svelte`: `canReembed = source.kind==='recording' && (source.status==='error' || ((source.chunk_count ?? 0)===0 && source.status==='ready')) && source.has_audio` を `$derived`。真なら `RefreshCw` ボタン(label `再生成`)を表示。
  - `SourcesPanel.svelte`: 録音は新クライアント `sourcesApi.recordingRetry(nb, sid)` を呼ぶ(文書 `retry()` には流さない)。呼出後 `upsertSource` で更新→ SSE が `RecordingConvStatus` を再駆動。
  - `lib/api/sources.ts` に `recordingRetry` 追加。`lib/api/types.ts::Source` に `has_audio` 追加。
- 検証: 0チャンク録音を用意→サイドバーに再生成ボタン→クリック→変換ステップ進行→チャンク生成→引用可能になることをスクショ確認。音源無し録音でボタンが出ないことも確認。

### #8 チャット待機UX
- 現状: 待機表示は `MessageList.svelte` L38 `{#if streaming && streamingText}` のため**最初のトークン前は何も出ない**。`ChatInput.svelte` L39 `disabled={disabled || !value.trim()}` で**空入力でもグレーアウト**。Ollama死活: `chat_stream` は `timeout=None` で詰まると無限待ち。`list_tags()`(GET /api/tags)は軽量プローブとして既存。Stopボタン無し(`cancel()` は実装済みだがUI未接続)。
- (a) 待機スピナー:
  - `MessageList.svelte`: `{#if conversationStore.streaming}` に変更し、`!streamingText` の間は「参照中…」(retrieval前/`streamingHits` 到着前)→ヒット到着後も最初のトークンまでは「生成中…」スピナーを表示。`SourceCard` のインラインスピナー(`Spinner`)の見た目を流用。トークン到着後は既存の部分Markdown+`生成中…` caret 表示へ遷移。
- (b) SSEハートビート + Stop:
  - サーバ: `chat.py::send_message`/`event_gen` で `EventSourceResponse` のハートビート(sse_starlette の ping 機能、または独自 `ping` イベントを ~15-30s 間隔で interleave)。最初のトークン前/無音区間でもビートが届く。
  - `core/generation/stream.py`: 必要なら `ping` GenerationEvent を区間に挿入(実装は ping をサーバ層に寄せるか stream 層に寄せるかは実装時に決定。SSE接続自体の生存が検知できれば良い)。
  - `core/ollama/client.py::chat_stream`: `httpx` の**読み取りタイムアウトを有限化**(例: 接続=既定、read=設定値)。詰まったOllamaが無限ハングせず例外→error イベントで表面化。
  - フロント `lib/api/chat.ts`: 未知イベントは現状無視。`ping` を受理し `conversation.svelte.ts` の `lastBeatAt` を更新。`streaming` 中に一定時間(例: 60s)ビート途絶→「Ollamaが応答していない可能性」警告表示。
  - **Stopボタン**: `ChatPanel`/`ChatInput` に、`streaming` 中は送信ボタンを **Stopボタンへ切替**(`conversationStore.cancel()` を接続)。詰まり/長時間時にユーザーが中断可能。
  - 死活間隔: ストリーム内ビートは ~15-30s(詰まり検知を機敏に)、ユーザー可視の「応答なし」警告は ~60s 途絶で。
- (c) 送信ボタンのトーンダウン是正:
  - `ChatInput.svelte`: 送信ボタンに渡す `disabled` を **`streaming`(返答待ち)のみ**にする。**空入力ではグレーアウトしない**(通常表示)。実送信は `submit()` 内で `value.trim()` を判定して空なら無反応(既存ガード)。
  - 返答待ち中も**テキストエリアは編集可**(次の質問を打てる)。ただし送信は `streaming` 解除後(または Stop 後)。
- 検証: 質問送信直後にスピナー(参照中→生成中)が出ること、空入力で送信ボタンが通常色のままなこと、返答待ち中に Stop で中断できること、Ollama停止時に~60sで警告が出ることをスクショ/操作で確認。

## 4. 横断方針 / 非機能
- 新規依存なし。既存 `Spinner`/`AudioCitationPlayer`/設定永続化パターン/`RefreshCw` 等を流用。
- 既存テスト(202件)を壊さない。新規バックエンドはユニット/統合テストを追加(retrieval スコープのフィルタ、`list_chunks_for_source`、recording retry の dispatch、`has_audio`)。
- SSEイベントの後方互換: 既存クライアントは未知イベント無視なので `ping` 追加は安全。`source_ids` 未指定時=全件で旧挙動維持。
- GUI変更は **Playwright実機スクショ検証**を各機能のゲートにする(自動テストGREENのみでのPASS禁止)。

## 5. 対象外(本仕様では扱わない)
- 群2: #2 モデル選択(LLM/埋め込み分離・分類・永続化・1024次元制約)、#3 保存先パス(sources_dir override)。
- 群3: #1 アクセラレータ(STTはCUDA/CPU維持、話者分離/Ollamaのみ他アクセラレータ・自動判定・設定UI)、#9 リモート推論(APIキー・opt-in・ローカル既定維持)。
- 既知繰り延べ: 声紋横断命名(Task 4.7)、`duration_ms` 配線。
