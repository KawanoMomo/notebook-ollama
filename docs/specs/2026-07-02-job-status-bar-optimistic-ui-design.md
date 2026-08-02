---
type: spec
title: ジョブ状態可視化 + Optimistic UI
summary: "並行ジョブの状態可視化とOptimistic UIで即時フィードバックを提供。"
aliases:
  - ジョブ状態バー
  - Optimistic UI
status: approved
status_inferred: true
date: 2026-07-02
project: NotebookOllama
area: rag-ux
tags:
  - spec
note: 実機検証レポート PASS 有り(docs/eval/2026-07-02-job-status-bar)
code:
  - apps/web/src/lib/components/JobStatusBar.svelte
  - apps/web/src/lib/stores/currentNotebook.svelte.ts
  - apps/web/src/lib/stores/events.svelte.ts
  - apps/web/src/routes/notebooks
  - core/adr/adr_job.py
  - core/storage/sources_repo.py
  - core/summary/summarizer.py
---

# ジョブ状態可視化 + Optimistic UI 設計 (2026-07-02)

## 背景

ユーザーから以下3つのUX上の不具合が報告された:

1. **並行入力の順序不明**: 要約(サマリ)生成ジョブが進行中に、ユーザーがチャットで質問を送信すると、両方の処理が同時に走り、どちらの入力がどう処理されているのかユーザーから見て分からない。
2. **ナビゲーション後の状態消失**: ADR生成のような長時間バックグラウンドジョブが進行中に、ユーザーが「戻る」でノート一覧画面に遷移すると、ノートが一覧に表示されないことがある。
3. **即時フィードバック欠如**: 録音の開始/停止ボタンをクリックしても、バックエンド処理が実際に動き出すまでUIに一切変化がなく、ユーザーは自分のクリックが本当に受理されたのか不安になる。

`deep-research` (Nielsen Norman Group 一次資料、Microsoft Azure Architecture Center、FastAPI/sveltekit-sse 公式ドキュメント等を3票中2票の反証チェックで検証) の結果、以下が確認された:

- **Visibility of System Status** (Nielsen 10原則の第1): システムは常に「今何が起きているか」を適切なタイミングでユーザーに伝えるべき。
- Progress indicator は「安心感を与える」と「同じ操作の連打を防ぐ」の二重の効果を持つ。
- Optimistic UI (クリック直後にサーバー応答を待たず成功を仮定した状態を描画) は、この種のフィードバック欠如を解決する標準パターン。
- ブラウザは HTTP/2 非使用時、オリジンごとに同時 SSE 接続を最大6本に制限する。ページ/コンポーネント単位で個別にSSEを張る設計は接続枯渇のリスクがある。

現状コード調査の結果:

- SSE購読 (`/api/notebooks/{id}/events`) はノート詳細ページの `onMount`/`onDestroy` に紐づいており、ページを離れると完全に切断される。
- Source の状態は3つの独立フィールドで管理される (`core/storage/sources_repo.py`):
  - `status`: pending / parsing / chunking / embedding / ready / error (取り込みパイプライン)
  - `summary_status`: generating / ready / error (要約ジョブ、nullable)
  - `adr_status`: generating / ready / error / skipped (ADRジョブ、nullable)
- バックエンドの要約/ADRジョブ (`core/summary/summarizer.py`、`core/adr/adr_job.py`) は状態遷移のたびに `summary_status` / `adr_status` を含むSSEイベントを `notebook:{id}` トピックへ正しく発行している。
- **しかしフロントのSSEハンドラ (`apps/web/src/lib/stores/events.svelte.ts` の `upsertSource` 呼び出し) は `status` / `chunk_count` / `embedded` しか patch せず、ペイロードに含まれる `summary_status` / `adr_status` を捨てている**。要約/ADR完了の再取得(ポーリング等)も存在しない。このため `currentNotebookStore.sources` 上のこれら2フィールドは、生成開始時のPOSTレスポンスによる楽観的更新(`generating`)以降、リアルタイムには更新されない。既存の SourceCard の生成中スピナーが完了後も止まらない潜在バグの疑いがある(実装時に実機で確認する)。
- チャット送信(`ChatInput.svelte`)と要約/ADR生成(`sources.py` の `summary_runner`/`adr_runner`)は完全に独立した非同期タスクとして実行され、排他制御・順序可視化は一切ない。
- `recordingStore.start()` はAPI応答を待ってから `recording = true` を設定しており、optimistic updateが存在しない。`stop()` は `clearTimer()`/`closeWs()` を即座に実行し、Source追加のみ楽観的に行っている。
- 録音変換パイプライン用に、SSEペイロードの `step` / `step_label` / `progress` を保持する既存機構 (`eventsStore.convStepFor(sourceId)`) がある。

## スコープ

**対象**: 上記の症状1(並行入力の可視化)と症状3(録音ボタンのoptimistic UI)。

**対象外**: 症状2(ADR生成中のナビゲーションでノートが一覧から消える)は、静的コード調査だけでは決定的な原因を特定できなかった実バグの可能性が高いため、本設計とは切り離し、別途 `systematic-debugging` スキルで実際に再現・原因特定した上で対応する。この設計のアーキテクチャ(グローバルなジョブ可視化)が副次的に解決する可能性はあるが、それを前提にはしない。

**可視化の範囲**: 「現在開いているノートの中だけ」とする。ノート一覧やタブをまたいだジョブ追跡は行わない(YAGNI)。将来、症状2の原因特定の結果によってはノート一覧側の表示が必要になる可能性があるが、その場合は別途検討する。

**処理自体の変更なし**: 要約/ADR生成とチャットの並列実行は現状のまま変更しない。本設計は「見えるようにする」だけであり、キュー化・排他制御は行わない(Ollama側が実際に並列処理可能であれば問題なく、実装コストも抑えられるため)。

## アーキテクチャ概要

新しいストアやSSE接続は追加しない。既存の `currentNotebookStore.sources` から `$derived` で「進行中ジョブ一覧」を導出する。ただし前提修正が1つ必要: 現状のSSEハンドラは `summary_status` / `adr_status` を捨てているため(上記調査結果)、まず `events.svelte.ts` の `upsertSource` にこの2フィールドの patch を追加する。バックエンドは既に発行済みなので、バックエンド変更は不要。

```
apps/web/src/lib/stores/events.svelte.ts (修正)
  └─ upsertSource() に summary_status / adr_status の patch を追加
     (ペイロードに含まれる場合のみ上書き。含まれない旧来イベントでは既存値を維持)

apps/web/src/lib/stores/currentNotebook.svelte.ts
  └─ activeJobs: $derived getter (新規追加)
       sources.filter(status が pending/parsing/chunking/embedding、
                      または summary_status === 'generating'、
                      または adr_status === 'generating')
       .map(job-status-bar 表示用の {sourceId, label} へ変換)

apps/web/src/lib/components/JobStatusBar.svelte (新規)
  └─ activeJobs を購読し、0件なら非表示、1件以上ならバー表示

apps/web/src/routes/notebooks/[id]/+page.svelte
  └─ .topbar と .cols の間に <JobStatusBar /> を追加
```

## 症状1: JobStatusBar

- 配置: ノート詳細ページの `.topbar` 直下、`.cols` の直前。
- 表示条件: 進行中ジョブが1件以上のときのみ表示。0件では高さゼロ(既存レイアウトに影響を与えない)。
- 表示内容: 進行中ジョブ1件につき1行。スピナー(既存 `Spinner.svelte` を再利用) + ラベル(例:「議事録.docx: 要約生成中」「議事録.docx: ADR生成中」)。同一ソースで複数ジョブ(取り込み中+要約中など)が同時進行する場合はジョブごとに別行。
- 進捗表示: 既存の `eventsStore.convStepFor(sourceId)`(`step_label` / `progress`)が値を持つジョブはそれを併記する。要約/ADRジョブが `step` を発行していない場合は不定スピナー+ラベルのみとする(架空の進捗数値は作らない)。
- チャットのストリーミング状態はこのバーに含めない。チャットの進行はチャットパネル自体のストリーミング表示で見えるため、バー(要約/ADR/取り込み)+チャットパネルの2箇所を合わせて「今何が並行して動いているか」が可視化される。
- 「進行中」の判定条件: `status ∈ {pending, parsing, chunking, embedding}`、`summary_status === 'generating'`、`adr_status === 'generating'`(enum定義 `core/storage/sources_repo.py` に基づく)。`error` / `skipped` は進行中として扱わない。

## 症状3: 録音ボタンの Optimistic UI

対象: 開始・停止の両方。

**開始 (`recordingStore.start()`)**
1. API呼び出し(`api.start()`)の**前**に、同期的に `starting = true` をセット。
2. UIは即座に disabled + スピナー + ラベル「録音開始中…」に変化。
3. API成功: `recording = true`、`starting = false`、WS接続(`connectWs`)。
4. API失敗: `starting = false` にロールバックし、既存の `pushToast` でエラー表示。`recording` は `false` のまま。

**停止 (`recordingStore.stop()`)**
1. API呼び出しの**前**に、同期的に `stopping = true` をセット。UIは即座に disabled + スピナー + ラベル「停止中…」に変化。
2. 既存通り `clearTimer()`/`closeWs()` は即座に実行(この設計では変更しない)。
3. API成功: `stopping = false`、既存の楽観的Source追加(`upsertSource(optimisticSource)`)を実行。
4. API失敗: `stopping = false` にロールバックし、`pushToast` でエラー表示。ただしWS/タイマーは既に停止済みのため「録音を再開する」ロールバックは行わない(音声キャプチャ自体が既に終了しているため技術的に無意味)。この場合ユーザーは録音停止済み・保存失敗という状態になり、エラートーストで明示する。

## エラーハンドリング

- Optimistic状態(`starting`/`stopping`)は必ず `try/finally` または同等の構造でAPI呼び出し失敗時にもリセットされることを保証する(ボタンが永久に disabled のまま固まることを防ぐ)。
- JobStatusBar は既存の `currentNotebookStore.sources` のエラー状態(`status === 'error'`)を進行中ジョブとして扱わない(エラーは別途 SourceCard 側で表示済み)。
- 本設計はSSE接続自体の新しいエラーハンドリングを追加しない(既存の `eventsStore` の再接続動作を変更しない)。

## テスト計画

- **Unit (vitest)**: `recordingStore.start()`/`stop()` の optimistic 状態遷移とAPI失敗時のロールバックを、既存のストアテストパターンに沿って検証。
- **Unit**: `currentNotebookStore` の `activeJobs` 導出ロジックを、`status` / `summary_status` / `adr_status` の各組み合わせ(複数ジョブ同時進行、error/skipped の除外を含む)で検証。
- **Unit**: `events.svelte.ts` のSSEハンドラが `summary_status` / `adr_status` を patch すること、ペイロードに含まれないイベントでは既存値を保持することを検証。
- **Playwright (実機検証、必須)**: ユーザーの恒久指示により、GUIに影響する変更は自動テストのGREENのみでPASS判定しない。以下を実機スクリーンショット付きで検証する:
  - 要約/ADR生成中にステータスバーが表示され、**完了後に消えること**(SSEハンドラ修正の実機確認を兼ねる。既存 SourceCard のスピナーが完了で止まることも合わせて確認)
  - 録音開始/停止ボタンをクリックした瞬間(バックエンド応答前)に見た目が変化すること
  - 録音API失敗時に正しくロールバック表示されること(Playwright の route interception で `/api/notebooks/*/recordings*` にエラー応答を注入して検証)

## 今後の課題 (本設計のスコープ外)

- 症状2(ADR生成中のナビゲーションでノートが一覧から消える)の原因特定と修正 — 別セッションで `systematic-debugging` により対応。
- ノート一覧をまたいだジョブ可視化(症状2の原因次第で必要になる可能性あり)。
- 要約/ADR生成とチャットの実際の排他制御・キュー化(現時点では不要と判断)。
