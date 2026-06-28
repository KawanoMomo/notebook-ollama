# Source Guide — 設計仕様書

> 作成: 2026-06-25  
> 対象: `10_NotebookOllama`  
> スコープ: ① デフォルト全選択 + 一括コントロール / ② 0件選択ブロック / ③ ソースガイド（要約）/ ④ 要約生成パイプライン

---

## 1. 概要

ソースパネルの UX を3点改善し、NotebookLM 本家に近い「ソースガイド」機能を追加する。

| 機能 | 変更内容 |
|---|---|
| デフォルト全選択 | 起動・ノート切替時に全ソースをチェック済みにする |
| 一括コントロール | トライステートの「すべてのソース」行を追加 |
| 0件選択ブロック | 送信無効化 + 警告バー（旧「0件=全件」挙動を廃止） |
| ソースガイド | 左パネル内でカード展開 → 要約を折りたたみ/展開 |
| 要約生成 | ドキュメント: 取込時自動 / 録音: 変換パイプライン Step 5 |

---

## 2. デフォルト全選択 + 一括コントロール

### 2.1 デフォルト状態

- `currentNotebookStore.load()` 完了時、取得した全ソースの ID を `selected` に設定する。
- 新規ソースが `upsertSource()` で追加された場合も自動でチェック状態にする。
- 選択状態はメモリのみ保持。ページリロード・ノート切替で全選択にリセットされる（永続化なし）。

### 2.2 トライステート「すべてのソース」行

`SourcesPanel.svelte` のヘッダー直下（検索ボックスの下、ソース一覧の上）に1行追加。

| 状態 | チェックボックス表示 | カウント表示 | クリック動作 |
|---|---|---|---|
| 全選択 | ■（塗り・チェック） | `N / N` | 全解除 |
| 一部選択 | ▣（塗り・ダッシュ） | `M / N` | 全解除 |
| 0件 | □（空） | `0 / N` | 全選択 |

- `store.selectAll()` と `store.clearSelection()` を新規追加する。
- フィルタ中（検索ボックスに入力あり）は、表示中ソースのみを対象に全選択/全解除する。

---

## 3. 0件選択時の挙動

チェック済みソースが0件の状態でチャットが開いているとき:

- `ChatInput` の送信ボタンを `disabled` にする。
- チャット入力エリアの直上にオレンジの警告バーを表示: `⚠ ソースが選択されていません。1つ以上選んでください。`
- 旧挙動（`source_ids` が空 = 全ソース検索）は廃止。バックエンド `send_message` は空配列の場合に 400 を返すよう修正する。

---

## 4. ソースガイド（要約）

### 4.1 場所と開き方

- **場所**: 右パネル（SourceViewer）ではなく、**左ソースパネルのカード内**。
- **トリガー**: ソースカードのタイトル部分（チェックボックス以外）をクリック。
- **展開**: クリックしたカードがその場で縦に伸び、下のカードが押し下げられる。
- **同時に**: 右パネルに原文を表示する（既存 `onSourceSelect` の動作は変更しない）。

### 4.2 展開エリアの構成

```
[▶ ソースガイド]  [↻ 再生成]    ← トグルヘッダー（常時表示）
────────────────────────────────
[要約本文 or スケルトン or エラー]  ← 折りたたみボディ
```

- `▶` アイコン: 展開時に 90° 回転（CSS transition）。クリックで本文を開閉。
- **デフォルト**: ソースをクリックした直後は**展開状態（open）**。
- 折りたたみ中はヘッダー行のみ残り、「ソースガイド」ラベルと「再生成」ボタンにアクセス可能。
- **キートピックは MVP から除外**（後日追加可能）。

### 4.3 要約本文の状態

| 状態 | 表示 |
|---|---|
| 生成中 | スケルトン3行 + `⟳ 要約を生成中…` |
| 完了 | 要約テキスト（1〜4文程度） |
| 失敗（3回リトライ後） | `⚠ 生成に失敗しました（3回） [↻ 再試行]` |

### 4.4 データモデル変更

`Source` スキーマに `summary` フィールドを追加する。

```python
class Source(BaseModel):
    ...
    summary: str | None = None           # LLM生成要約テキスト（未生成/失敗時は None）
    summary_status: str | None = None    # None=未生成 / "generating" / "ready" / "error"
```

`summary_status` の状態遷移:

```
None ──(取込完了)──→ "generating" ──(成功)──→ "ready"
                                  └─(3回失敗)──→ "error"
"error" ──(手動再試行)──→ "generating"
```

DB: `sources` テーブルに `summary TEXT` と `summary_status TEXT` カラムを追加（マイグレーション）。

---

## 5. 要約生成パイプライン

### 5.1 ドキュメント（PDF / MD / TXT / DOCX 等）

- 取込時の `EmbeddingJob` 完了直後に非同期で `SummaryJob` を起動する。
- `SummaryJob` の実装:
  1. ソースの全チャンクテキストを結合（最大 4000 トークンに切り詰め）して LLM に投入。
  2. プロンプト: 「以下の文書を3〜5文で日本語要約してください」
  3. 成功時: `summary_status = "ready"`, `summary = <テキスト>` を保存。
  4. 失敗時: 内部リトライ（最大3回、exponential backoff）。3回とも失敗で `summary_status = "error"`。
- ユーザーへのエラー通知は「3回失敗後」にのみ行う（SourceCard が `summary_status = "error"` を読んで表示）。
- 再生成ボタン押下時: `summary_status = "generating"` にリセット → `SummaryJob` を再実行。

### 5.2 録音（WAV 変換後）

録音変換パイプライン（`RecordingConvStatus`）に **Step 5「要約生成」を追加**。

```
Step 1: STT（Whisper）
Step 2: 話者分離（sherpa-onnx）
Step 3: タイトル生成（LLM）  ← 既存の name_inference.py
Step 4: Embedding（Qdrant）
Step 5: 要約生成（LLM）      ← 今回追加
```

- `title_inference.py` と同じ非同期パターンで実装。
- 3回失敗後のみ `summary_status = "error"` をセットし、ユーザーに手動再試行を促す。

### 5.3 SSE による UI 更新

`summary_status` が `"generating"` → `"ready"` or `"error"` に変化したとき、既存の SSE イベントストリームを通じてフロントに通知する。フロントは受信次第 `SourceCard` の表示を自動更新する（ポーリング不要）。

---

## 6. 変更ファイル一覧（概算）

| ファイル | 変更内容 |
|---|---|
| `core/storage/sources_repo.py` | `summary` / `summary_status` カラム CRUD |
| `core/storage/migrations/` | スキーマ追加マイグレーション |
| `core/summary/summarizer.py` | 新規: LLM要約ジョブ（3回リトライ込み） |
| `core/ingest/pipeline.py` | ドキュメント取込後に SummaryJob 起動 |
| `core/recording/recording_pipeline.py` | Step 5 として SummaryJob 追加 |
| `apps/api/schemas/source.py` | `summary` / `summary_status` フィールド追加 |
| `apps/api/routers/sources.py` | 再生成エンドポイント追加 `POST /sources/{id}/summarize` |
| `apps/api/routers/chat.py` | `source_ids` 空配列で 400 を返す |
| `apps/web/src/lib/stores/currentNotebook.svelte.ts` | `selectAll()` 追加、`load()` で全選択 |
| `apps/web/src/lib/components/SourcesPanel.svelte` | トライステート行追加 |
| `apps/web/src/lib/components/SourceCard.svelte` | カード展開 + ソースガイドエリア追加 |
| `apps/web/src/lib/components/ChatInput.svelte` | 0件選択時に disabled + 警告バー |
| `apps/web/src/lib/api/sources.ts` | `summarize()` API 呼び出し追加 |

---

## 7. 対象外（MVP スコープ外）

- キートピック（後日追加可能）
- 要約の永続化をブラウザ側に持つ（サーバー側 DB のみ）
- 要約の自動言語検出（日本語固定）
- 選択状態の永続化（localStorage 等）

---

## 8. モック

`docs/mocks/sources-summary-ui-moc.html`（v3 合意済み）
