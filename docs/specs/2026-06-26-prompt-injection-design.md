---
type: spec
title: Prompt Injection(プロンプト挿入ツールバー)
summary: "チャット入力欄上に定型プロンプト挿入ツールバー(設定登録→ワンクリック発火)。"
aliases:
  - プロンプト挿入
  - Prompt Injection
status: approved
status_inferred: true
date: 2026-06-26
project: NotebookOllama
area: prompts
tags:
  - spec
---

# Prompt Injection — 設計仕様書

> 作成: 2026-06-26
> 対象: `10_NotebookOllama`
> スコープ: チャット入力欄上に「プロンプト挿入ツールバー」を追加し、設定画面から登録した定型プロンプトをワンクリック / プルダウン経由で即発火できるようにする

---

## 1. 概要

頻繁に使うプロンプト(「要約して」「英語に翻訳」など)を毎回入力する手間をなくす。

| 構成 | 説明 |
|---|---|
| 固定ボタン3スロット | チャット入力欄上の左側。1クリック即送信 |
| プルダウン + 「発行」ボタン | 同列右側。任意件数のプロンプトを格納。選択 → 発行で送信 |
| 設定画面「プロンプト」セクション | スロット/プルダウンの登録・編集・並び替え・アイコン画像アップロード・Markdown インポート |

選択中のソース(チェックボックス ON)が文脈となり、既存チャットパイプラインに乗ってストリーミング応答が流れる。プロンプト発火経路は **既存 `POST /api/chat/messages` をそのまま再利用** し、バックエンドのチャット側にプロンプト機能の認識は持たせない。

---

## 2. UI 設計

### 2.1 ChatInput ツールバー(新規 `PromptToolbar.svelte`)

`ChatInput.svelte` の textarea のすぐ上に1行追加。

```
┌────────────────────────────────────────────────────────┐
│ [icon1] [icon2] [icon3] | ▾ その他プロンプト  [発行] │  ← PromptToolbar
├────────────────────────────────────────────────────────┤
│ textarea(質問を入力 Cmd/Ctrl+Enter で送信)            │  ← 既存
└────────────────────────────────────────────────────────┘
```

- 固定ボタン: 32×32px、`title` 属性でツールチップ。アイコン画像がある場合は `<img>`、無い場合はタイトル頭文字1文字をテキスト表示。
- 未設定スロットは **DOM に出さない**(`v-if` 風の完全非表示)。3枠全て未設定 + プルダウン空ならツールバー自体を描画しない(degraded mode = 既存 UI と同等)。
- プルダウン: `<select>`。未選択時は「その他プロンプト ▾」のプレースホルダ。
- 「発行」ボタン: プルダウンが未選択時 disabled。クリックで選択 prompt の `body` を送信、選択をリセット。
- ツールバー全体は `streaming === true` または `sourcesSelected === 0` のとき disabled(既存 `ChatInput.svelte` の判定をそのまま継承)。

### 2.2 設定画面「プロンプト」セクション(`routes/settings/+page.svelte` 拡張)

左ナビ「LLM / 生成」グループの最下段に「プロンプト」項目を追加。中身は2ブロック。

#### 2.2.1 固定ボタン(3カード)

各スロットを独立した編集カードとして縦に並べる。

| 要素 | 説明 |
|---|---|
| アイコンプレビュー(48×48) | 画像があれば表示、無ければ title 頭文字1文字 |
| 「画像を選択…」「画像を削除」 | PNG/JPG/SVG ファイル選択。アップロード即時保存 |
| タイトル入力 | テキスト1行(max 100文字) |
| プロンプト本文 textarea | マルチライン(max 10,000文字)。等幅フォント |
| 「Markdown ファイルからインポート…」 | `.md`/`.markdown` を選び textarea に流し込む。ファイル選択完了時にロードのみ、保存は別途 |
| 「スロットを空に」「保存」ボタン | カード末尾 |

#### 2.2.2 プルダウン候補(テーブル + 編集モーダル)

任意件数(最大100件)のテーブル表示。各行に上下矢印・編集・削除アイコン。「+ プルダウンに追加」ボタンで新規行作成。

編集/追加は `Modal.svelte` を使い回したモーダルで実施。中身は固定スロットと同じ「タイトル + プロンプト本文(Markdown インポート可)」フォーム。

並び替えは上/下矢印1クリックで隣の行と入れ替え。先頭の「↑」と末尾の「↓」は disabled。

### 2.3 既存 UI との一貫性

- 既存 `app.css` の CSS 変数(`--color-accent`, `--space-*`, `--radius-*` 等)とコンポーネント(`Button`, `Modal`, `Toast`)を再利用
- 警告色、disabled スタイル、ボタンサイズ、フォントは既存設定画面と完全に同一
- アイコンは Lucide(`@lucide/svelte`)から選定(`Upload`, `Trash2`, `Edit2`, `ArrowUp`, `ArrowDown`, `Send`, `FileText`)

---

## 3. データモデル

### 3.1 `core/settings_store.py` への追加

```python
class FixedPromptSlot(BaseModel):
    """固定ボタン1スロット。長さ3の list で常に保持。"""
    title: str = ""           # 空文字 = スロット未設定
    body: str = ""
    icon_filename: str | None = None  # data_dir/prompt-icons/ 配下のファイル名

class DropdownPrompt(BaseModel):
    id: str                   # uuid v4。並び替え/編集/削除のキー
    title: str
    body: str

class PromptsSettings(BaseModel):
    fixed: list[FixedPromptSlot]  # 常に長さ3
    dropdown: list[DropdownPrompt]  # 順序が表示順そのもの
```

`AppSettings` に `prompts: PromptsSettings` を追加。`settings.json` 読み込み時に `prompts` キーが無ければデフォルト(`fixed=[空,空,空], dropdown=[]`)を入れる。

### 3.2 「未設定」判定

固定スロットの未設定は **`title.strip() == ""` または `body.strip() == ""`**(どちらか欠落でも非表示)。`title` は表示・ツールチップに、`body` は発火に必須なので、両方揃ったときだけ「使えるスロット」とみなす。`None` は使わず空文字で揃える(既存 settings の流儀)。

### 3.3 制限値

| 項目 | 制限 |
|---|---|
| `title` | 最大100文字 |
| `body` | 最大10,000文字 |
| `dropdown` 件数 | 最大100件 |
| アイコン画像 | 200KB、PNG/JPG/SVG、最大辺512px(超える場合はアップロード時にエラー応答、自動リサイズは行わない) |

---

## 4. API 設計

### 4.1 新規ルータ `apps/api/routers/prompts.py`

| メソッド | パス | 用途 |
|---|---|---|
| `GET` | `/api/prompts` | 全プロンプト設定取得 |
| `PUT` | `/api/prompts/fixed/{slot_index}` | 固定スロット上書き(0/1/2)、body `{title, body}` |
| `DELETE` | `/api/prompts/fixed/{slot_index}` | スロットを空に。アイコン画像も削除 |
| `POST` | `/api/prompts/fixed/{slot_index}/icon` | 画像アップロード(multipart/form-data)。旧画像は置換破棄 |
| `DELETE` | `/api/prompts/fixed/{slot_index}/icon` | 画像のみ削除(title/body は残す) |
| `GET` | `/api/prompts/icons/{filename}` | 画像配信(`FileResponse`) |
| `POST` | `/api/prompts/dropdown` | プルダウン項目追加(末尾)。body `{title, body}` → サーバが `id` 採番 |
| `PUT` | `/api/prompts/dropdown/{id}` | 1件編集 |
| `DELETE` | `/api/prompts/dropdown/{id}` | 1件削除 |
| `PUT` | `/api/prompts/dropdown/order` | 並び替え。body `{ids: [...]}` で完全な順序を一括指定 |

### 4.2 プロンプト「発火」自体は新規 API 不要

固定ボタン / プルダウン発行時の送信は、既存 `conversationStore.send(notebookId, body, sourceIds)` をそのまま呼ぶ。バックエンドは何も変更なし(疎結合)。

### 4.3 画像配信

- 保存先: `<data_dir>/prompt-icons/<uuid>.<ext>` (`<ext>` は MIME から決定)
- 配信: `FileResponse` を返すルータ単発。`Cache-Control: public, max-age=86400`
- セキュリティ: `os.path.basename` で正規化 + UUIDフォーマット正規表現で path traversal を弾く

### 4.4 並び替え API の設計判断

`PUT /dropdown/order { ids: [...] }` 採用。クライアントが現在の全 `id` を順序通りに渡す。

採用理由: 競合に強い・複数移動を1往復で表現できる・上限100件なのでペイロードも軽い。

### 4.5 スキーマ `apps/api/schemas/prompts.py`

```python
class FixedPromptSlotOut(BaseModel):
    title: str
    body: str
    icon_url: str | None  # None または "/api/prompts/icons/<uuid>.<ext>"

class DropdownPromptOut(BaseModel):
    id: str
    title: str
    body: str

class PromptsOut(BaseModel):
    fixed: list[FixedPromptSlotOut]
    dropdown: list[DropdownPromptOut]

class FixedPromptSlotUpdate(BaseModel):
    title: str = Field(max_length=100)
    body: str = Field(max_length=10000)

class DropdownPromptCreate(BaseModel):
    title: str = Field(max_length=100)
    body: str = Field(max_length=10000)

class DropdownPromptUpdate(DropdownPromptCreate):
    pass

class DropdownOrderUpdate(BaseModel):
    ids: list[str]
```

ストレージ層(`FixedPromptSlot.icon_filename`)と API 層(`FixedPromptSlotOut.icon_url`)を分離し、URL組み立てはサーバ側で完結させる。

---

## 5. フロントエンド構造

### 5.1 新規ファイル

| ファイル | 役割 |
|---|---|
| `apps/web/src/lib/components/PromptToolbar.svelte` | ChatInput 上に乗るツールバー |
| `apps/web/src/lib/components/settings/PromptsSection.svelte` | 設定画面の「プロンプト」セクション本体 |
| `apps/web/src/lib/components/settings/FixedSlotCard.svelte` | 固定スロット1枠の編集カード |
| `apps/web/src/lib/components/settings/DropdownPromptEditModal.svelte` | プルダウン編集モーダル |
| `apps/web/src/lib/stores/prompts.svelte.ts` | プロンプト設定の状態管理 |
| `apps/web/src/lib/api/prompts.ts` | バックエンド API クライアント |

### 5.2 既存ファイルへの変更

| ファイル | 変更点 |
|---|---|
| `apps/web/src/lib/components/ChatInput.svelte` | textarea の上に `<PromptToolbar>` を差し込み。`onSend` を再利用 |
| `apps/web/src/routes/settings/+page.svelte` | 左ナビに「プロンプト」項目追加、`section==='prompts'` で `<PromptsSection>` を描画 |

### 5.3 `promptsStore` API

```ts
interface PromptsStore {
  readonly prompts: PromptsOut | null;
  readonly loading: boolean;
  readonly error: string | null;

  load(): Promise<void>;
  saveFixed(slot: 0 | 1 | 2, title: string, body: string): Promise<void>;
  clearFixed(slot: 0 | 1 | 2): Promise<void>;
  uploadIcon(slot: 0 | 1 | 2, file: File): Promise<void>;
  deleteIcon(slot: 0 | 1 | 2): Promise<void>;

  addDropdown(title: string, body: string): Promise<DropdownPromptOut>;
  updateDropdown(id: string, title: string, body: string): Promise<void>;
  deleteDropdown(id: string): Promise<void>;
  moveDropdown(id: string, delta: -1 | 1): Promise<void>;
}
```

---

## 6. エラー処理

### 6.1 バックエンド

| ケース | レスポンス |
|---|---|
| `slot_index` が 0/1/2 以外 | `400` `{"detail":"slot_index must be 0, 1, or 2"}` |
| `title` / `body` 文字数超過 | `422`(Pydantic 自動) |
| プルダウン `id` 不存在 | `404` |
| プルダウン 101件目の追加 | `400` `{"detail":"dropdown limit exceeded (max 100)"}` |
| 並び替え `ids` 不整合 | `400` `{"detail":"ids must contain exactly the current dropdown ids"}` |
| 画像 MIME 不正(magic number 判定) | `415` `{"detail":"only PNG/JPG/SVG are allowed"}` |
| 画像サイズ超過 | `413` `{"detail":"image must be <= 200KB"}` |
| SVG 内に `<script>` / `on[a-z]+\s*=` | `400` `{"detail":"SVG must not contain scripts"}` |
| 画像配信で path traversal 試行 | `400` |
| 同時書込み競合 | `asyncio.Lock` を `prompts` キーに掛けて直列化 |

### 6.2 フロントエンド

| ケース | UI 反応 |
|---|---|
| 保存成功 | `pushToast('スロットを保存しました', 'success')` |
| 保存失敗 | `pushToast(err.message, 'error')`、フォーム値保持 |
| アイコン形式/サイズ不正 | クライアント側で先に検証してサーバ往復を節約 |
| Markdown インポートで非 `.md` | `pushToast(...)` で警告、textarea 変更なし |
| Markdown が 10,000文字超 | `pushToast(...)` でエラー、textarea 変更なし |
| 並び替え連打 | `await` で順序保証、進行中はボタン disabled |
| ツールバー: ソース0件 / streaming中 | 全要素 disabled |
| ツールバー: プルダウン未選択 | 「発行」ボタン disabled |
| 設定 API ロード失敗 | ツールバー非表示で degraded、コンソール warn |

---

## 7. テスト方針

### 7.1 バックエンド単体 `tests/unit/test_prompts_store.py`

- 初期値: `prompts` キー欠落 → デフォルトでロード成功
- 固定スロット境界(0文字、上限、超過)
- スロットクリアで完全空に
- プルダウン CRUD: 追加で uuid 採番、編集で id 維持、削除
- 並び替え整合性(完全一致のみ成功)
- 100件上限

### 7.2 バックエンド統合 `tests/integration/test_prompts_api.py`

`TestClient` + `tmp_path` で `data_dir` 差し替え。

- 全エンドポイントのハッピーパス往復(GET→PUT→GET で永続化確認)
- 画像アップロード: 200KB 通過、201KB で `413`
- MIME 詐称: 拡張子 `.png` で実体 GIF を投げて `415`
- SVG XSS: `<script>` 入り SVG で `400`
- パス traversal: `..%2F..%2Fetc%2Fpasswd` で `400`
- 並び替え不整合で `400`、正しい順序で `200`
- 固定スロット DELETE で `prompt-icons/` ファイルが消える

### 7.3 フロント単体

`apps/web/tests/unit/PromptToolbar.test.ts`:
- 全未設定 + プルダウン空 → ツールバー描画されない
- スロット1のみ設定 → ボタン1個
- title=「要約」、icon_url なし → 「要」が描画
- ボタンクリック → `onSend(body)` 呼ばれる
- プルダウン選択 → 「発行」が enabled
- 「発行」クリック → `onSend(選択肢 body)` + 選択リセット
- `streaming=true` / `sourcesSelected=0` → 全 disabled

`apps/web/tests/unit/promptsStore.test.ts`:
- 読み込み失敗で `prompts === null`
- 並び替えロジック(順序操作の純粋関数)

### 7.4 E2E `apps/web/tests/e2e/prompts.spec.ts`(Playwright)

**Visual verification 必須**(CLAUDE.md の GUI 変更ルール)。各シナリオでスクショを残し、`evaluator` エージェントが PASS 判定。

1. 設定 → スロット1 を設定(タイトル/本文/PNGアイコン)→ 保存 → リロードして再表示
2. ホーム → ソース3件チェック → スロット1ボタン押下 → ストリーミング開始
3. プルダウン項目を「発行」ボタンで送信
4. プルダウンを上下矢印で並べ替え → リロードで順序保持
5. ソース0件でツールバー全 disabled
6. Markdown インポート: `.md` ファイル選択 → textarea に内容反映 → 保存

### 7.5 優先順位

| レイヤ | 優先度 | 理由 |
|---|---|---|
| 単体(unit) | 高 | リファクタ耐性、CI 高速 |
| 統合(integration) | 高 | API 契約と永続化を一気に確定 |
| フロント単体 | 中 | 分岐網羅 |
| E2E | **必須** | GUI 変更で自動テスト GREEN だけでは visual regression 検出不可 |

---

## 8. 非スコープ(YAGNI)

明示的に **やらない** と決めた事項。後で「やるべきだった」議論を防ぐためにここに残す。

- プロンプト本文の変数置換(`{{selected_sources}}` 等のテンプレートエンジン): ユーザ判断でスコープ外
- ノートブック単位のプロンプトセット(グローバル共通のみ)
- プロンプトの共有/エクスポート/インポート機能(個別 Markdown インポートのみ)
- プロンプト使用履歴・統計
- ドラッグ&ドロップ並び替え(上下矢印のみ)
- ホットキー割り当て(Cmd/Ctrl+1/2/3 で固定ボタン発火など)
- プロンプト本文の Markdown プレビュー(LLM 側が解釈するだけなので不要)

---

## 9. 影響範囲まとめ

### 9.1 新規ファイル

- `apps/api/routers/prompts.py`
- `apps/api/schemas/prompts.py`
- `apps/web/src/lib/components/PromptToolbar.svelte`
- `apps/web/src/lib/components/settings/PromptsSection.svelte`
- `apps/web/src/lib/components/settings/FixedSlotCard.svelte`
- `apps/web/src/lib/components/settings/DropdownPromptEditModal.svelte`
- `apps/web/src/lib/stores/prompts.svelte.ts`
- `apps/web/src/lib/api/prompts.ts`
- `tests/unit/test_prompts_store.py`
- `tests/integration/test_prompts_api.py`
- `apps/web/tests/unit/PromptToolbar.test.ts`
- `apps/web/tests/unit/promptsStore.test.ts`
- `apps/web/tests/e2e/prompts.spec.ts`

### 9.2 変更ファイル

- `core/settings_store.py` — `PromptsSettings` 追加 + デフォルト値
- `apps/api/main.py` — `prompts` ルータマウント
- `apps/web/src/lib/components/ChatInput.svelte` — `<PromptToolbar>` 差し込み
- `apps/web/src/routes/settings/+page.svelte` — 「プロンプト」セクション追加

### 9.3 既存挙動への非干渉

- `ChatInput` の `noSourcesSelected` / `streaming` 判定はそのまま継承
- 既存チャット API/SSE/会話履歴ロジックは変更なし
- 既存設定(audio, ollama, generation, retrieval, storage)は影響なし
