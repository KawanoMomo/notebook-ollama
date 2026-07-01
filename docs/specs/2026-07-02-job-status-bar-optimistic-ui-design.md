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
- `currentNotebookStore.sources` は当該SSEイベント (`source_status`) を受けて `upsertSource()` で既にリアクティブに更新されている。
- チャット送信(`ChatInput.svelte`)と要約/ADR生成(`sources.py` の `summary_runner`/`adr_runner`)は完全に独立した非同期タスクとして実行され、排他制御・順序可視化は一切ない。
- `recordingStore.start()` はAPI応答を待ってから `recording = true` を設定しており、optimistic updateが存在しない。`stop()` は `clearTimer()`/`closeWs()` を即座に実行し、Source追加のみ楽観的に行っている。

## スコープ

**対象**: 上記の症状1(並行入力の可視化)と症状3(録音ボタンのoptimistic UI)。

**対象外**: 症状2(ADR生成中のナビゲーションでノートが一覧から消える)は、静的コード調査だけでは決定的な原因を特定できなかった実バグの可能性が高いため、本設計とは切り離し、別途 `systematic-debugging` スキルで実際に再現・原因特定した上で対応する。この設計のアーキテクチャ(グローバルなジョブ可視化)が副次的に解決する可能性はあるが、それを前提にはしない。

**可視化の範囲**: 「現在開いているノートの中だけ」とする。ノート一覧やタブをまたいだジョブ追跡は行わない(YAGNI)。将来、症状2の原因特定の結果によってはノート一覧側の表示が必要になる可能性があるが、その場合は別途検討する。

**処理自体の変更なし**: 要約/ADR生成とチャットの並列実行は現状のまま変更しない。本設計は「見えるようにする」だけであり、キュー化・排他制御は行わない(Ollama側が実際に並列処理可能であれば問題なく、実装コストも抑えられるため)。

## アーキテクチャ概要

新しいストアやSSE配線は追加しない。既存の `currentNotebookStore.sources`(ノート詳細ページ滞在中のみ有効、SSEで既にリアクティブ更新済み)から `$derived` で「進行中ジョブ一覧」を導出する。

```
apps/web/src/lib/stores/currentNotebook.svelte.ts
  └─ activeJobs: $derived getter (新規追加)
       sources.filter(進行中とみなせる status/adr_status)
       .map(job-status-bar 表示用の {sourceId, label} へ変換)

apps/web/src/lib/components/JobStatusBar.svelte (新規)
  └─ activeJobs を購読し、0件なら非表示、1件以上ならバー表示

apps/web/src/routes/notebooks/[id]/+page.svelte
  └─ .topbar と .cols の間に <JobStatusBar /> を追加
```

## 症状1: JobStatusBar

- 配置: ノート詳細ページの `.topbar` 直下、`.cols` の直前。
- 表示条件: 進行中ジョブが1件以上のときのみ表示。0件では高さゼロ(既存レイアウトに影響を与えない)。
- 表示内容: 進行中ジョブ1件につき1行。スピナー(既存 `Spinner.svelte` を再利用) + ラベル(例:「議事録.docx: 要約生成中」「議事録.docx: ADR生成中」)。
- 進捗率(ステップ番号等)は、実装時に既存のSSEペイロードに含まれているか確認し、含まれていれば表示、なければ不定スピナー+ラベルのみとする(架空の進捗数値は作らない)。
- チャットのストリーミング状態はこのバーに含めない(チャットパネル自体に既に表示されており、重複を避ける)。
- `activeJobs` の判定条件(どの `status`/`adr_status` の値を「進行中」とみなすか)は、実装時に `core/` 側の実際の状態遷移(enum定義)を確認して確定する。

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
- **Unit**: `currentNotebookStore` の `activeJobs` 導出ロジックを、各種 `status`/`adr_status` の組み合わせで検証。
- **Playwright (実機検証、必須)**: ユーザーの恒久指示により、GUIに影響する変更は自動テストのGREENのみでPASS判定しない。以下を実機スクリーンショット付きで検証する:
  - 要約/ADR生成中にステータスバーが表示され、完了後に消えること
  - 録音開始/停止ボタンをクリックした瞬間(バックエンド応答前)に見た目が変化すること
  - 録音API失敗時に正しくロールバック表示されること(モック/エラー注入で検証)

## 今後の課題 (本設計のスコープ外)

- 症状2(ADR生成中のナビゲーションでノートが一覧から消える)の原因特定と修正 — 別セッションで `systematic-debugging` により対応。
- ノート一覧をまたいだジョブ可視化(症状2の原因次第で必要になる可能性あり)。
- 要約/ADR生成とチャットの実際の排他制御・キュー化(現時点では不要と判断)。
