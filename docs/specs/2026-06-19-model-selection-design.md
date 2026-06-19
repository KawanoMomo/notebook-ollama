# Ollama モデル選択(LLM / 埋め込み)切替 設計仕様

> 対象: 群2 #2「Ollama モデルの切り替え」。チャットLLMと埋め込みモデルを分類し、誤選択を防ぎつつ切替可能にする。
> 群2 #3(保存先パス)・群3(#1 アクセラレータ / #9 リモート推論)は本仕様の対象外。

作成日: 2026-06-19 / ブランチ: `feature/model-selection`(`feature/recording-naming` の上に積む。master 直接編集禁止)。

## 1. 目的
- Ollama に入っているモデルを **チャットLLM** と **埋め込みモデル** に分類し、UI で用途別に正しく選べるようにする(埋め込みモデルをチャットに選ぶ等の誤選択を防ぐ)。
- チャットLLM は **全体既定 + ノートブックごと上書き** の2層で選べるようにする。
- 埋め込みモデルは **任意のモデルを選択可**。ただし選んだモデルの次元が現行インデックス(既存チャンクは bge-m3 / 1024次元)と異なる場合は **警告**し、切替は **全チャンク再インデックス**を伴うことを明示する。

## 2. 決定事項(確定)
| 項目 | 決定 |
|---|---|
| LLM 選択スコープ | **全体既定 + ノートブックごと上書き**。ノート未指定時は全体既定にフォールバック(`nb.default_model or config.ollama.default_model`、既に結線済み)。 |
| 埋め込み選択 | **任意モデル可。次元が変わる場合は警告**を出す。実際の切替は collection 再作成 + 全チャンク再埋め込み(再インデックス)を伴う。 |
| モデル分類 | Ollama `/api/show` の `capabilities` を一次情報、名前ヒューリスティックをフォールバックに、`chat` / `embedding` / `both` / `unknown` を判定。`/api/models` に `kind` を追加。 |
| 全体既定の永続化 | 新規 `PUT /api/settings/ollama` で `default_model` を更新し `settings.json` の `ollama` セクションに保存。起動時 `apply_overrides` を `ollama` にも拡張。 |
| 埋め込み切替の反映 | 再インデックス完了時に in-memory(`cfg.ollama.embedding_model` + VectorStore dim)へ即時反映し、`settings.json` に `embedding_model` / `embedding_dim` を永続化。LLM 既定は保存後すぐ反映。 |

## 3. 現状(実コード根拠)
| 要素 | 現状 | 必要作業 |
|---|---|---|
| ノートブックごとLLM | `apps/api/routers/chat.py:93` で `nb.default_model or config.ollama.default_model`。`PATCH /api/notebooks/{id}`(`NotebookUpdate.default_model`)で設定可。 | **UIピッカー追加のみ**。バックエンドは既存。 |
| 全体既定LLM | `core/config.py OllamaSettings.default_model="qwen2.5:14b"`。設定UI(`routes/settings/+page.svelte` `section==='models'`)は読み取り専用 `<dd>`。`PUT` なし。`apply_overrides` は `audio` のみ。 | PUT 追加 + 永続化 + 起動時適用 + UI を `<select>` 化。 |
| 埋め込みモデル | `config.ollama.embedding_model="bge-m3"`。3経路(`IngestionPipeline`/`RetrievalService`/`RecordingPipeline`)が `build_context` 時に `config.ollama.embedding_model` を読む。`apps/api/dependencies.py:18 _EMBEDDING_DIM=1024` ハードコード、`VectorStore(dim=_EMBEDDING_DIM)`。 | dim を動的化、切替=再インデックス、UI を `<select>`+警告 化。 |
| モデル一覧 | `apps/api/routers/models.py /api/models` が name/size/`context_window`/`recommended_for`(`classify_recommendation`)を返す。`OllamaClient.show()` は `/api/show` の生 json(新しい Ollama は `capabilities` を含む)を返す。 | `kind` 追加。`embedding_dim`(任意・後述)追加。 |
| チャンク本文 | `core/storage/chunks_repo.py` `ChunkRecord.text`(+`page/heading_path/ord/start_ms/end_ms/speaker`)を SQLite 永続化。`list_chunks_for_source`/`get_chunks_by_ids` あり。 | 再インデックスで全チャンクを再埋め込み可能(本文・メタ保持)。 |

## 4. 機能別設計

### (A) モデル分類(chat / embedding)
- `core/ollama/models_info.py` に追加:
  - `classify_kind(*, capabilities: list[str], name: str) -> str`(返り値 `"chat" | "embedding" | "both" | "unknown"`)。
    - 一次: `capabilities`(Ollama 0.5+ の `/api/show` が返す配列)。`"embedding"` を含めば embedding 寄り、`"completion"` または `"chat"` を含めば chat 寄り。両方→`both`、片方→該当、空→フォールバックへ。
    - フォールバック(名前ヒューリスティック): 小文字名に `embed` / `bge` / `nomic-embed` / `mxbai` / `snowflake-arctic-embed` / `all-minilm` を含めば `embedding`、それ以外は `chat`。判定不能は `unknown`。
- `apps/api/routers/models.py list_models`: 各モデルで `show.get("capabilities", [])` を取得し `kind = classify_kind(...)` を付与。レスポンスの各 model に `kind` を追加。
- `apps/api/schemas`(新規 or 既存 models 用)+ フロント `ModelInfo` 型(`apps/web/src/lib/api/types.ts`)に `kind: "chat" | "embedding" | "both" | "unknown"` を追加。
- 検証(ユニット): capabilities 優先・フォールバック・両対応(`both`)の各ケースで期待 kind を返す。

### (B) チャットLLM 選択(全体既定 + ノートブックごと)

#### (B-1) 全体既定 LLM
- スキーマ: `apps/api/schemas/settings.py` に書込用 `OllamaSettingsUpdate(BaseModel)`(`default_model: str`)を追加(既存 `OllamaSettingsSchema` は読取専用のまま)。
- エンドポイント: `apps/api/routers/settings.py` に `PUT /api/settings/ollama`(body `OllamaSettingsUpdate`)。
  - バリデーション: `list_tags()` に存在し、`classify_kind` が `chat` または `both` であること。違反は `INPUT_INVALID`(HTTP 400)。
  - in-memory: `cfg.ollama = cfg.ollama.model_copy(update={"default_model": body.default_model})`。
  - 永続化: `save_section(cfg.data_dir, "ollama", {"default_model": body.default_model, "embedding_model": cfg.ollama.embedding_model, "embedding_dim": <現行dim>})`(セクションは「現在値の総体」を書く。audio と同じ方式)。
  - 返り値: 更新後 `OllamaSettingsSchema`。
- 起動時適用: `core/settings_store.py apply_overrides` を拡張し、`ollama` セクションがあれば `cfg.ollama` にマージ適用(audio と同じく型不正時は既定で続行)。`default_model` のみ適用対象(`embedding_model`/`embedding_dim` の適用は (C) を参照)。
- フロント:
  - `apps/web/src/lib/api/settings.ts` に `putOllama({default_model})`。
  - `routes/settings/+page.svelte` `section==='models'` の「既定モデル」`<dd>` を `<select>`(chat/both のみ)に変更。`onchange` → `putOllama` → トースト。失敗時はエラー表示し選択を元に戻す。
  - `apps/web/src/lib/stores/settings.svelte.ts` に楽観更新 or 再 `load()`。
- 検証(統合): chat-capable を選ぶと 200 + `settings.json` の `ollama.default_model` 更新。embedding-only を選ぶと 400。

#### (B-2) ノートブックごと上書き
- バックエンド: 既存 `PATCH /api/notebooks/{id}`(`default_model`)を流用(変更なし)。`default_model=null` で全体既定に戻す。
- フロント:
  - `routes/notebooks/[id]/+page.svelte` の `.topbar`(現在は戻る + ノート名のみ)にモデルピッカー(小さい `<select>`、ラベル「このノートのモデル」)を追加。
    - 先頭 option = `既定 (＝{全体既定名})` → 選択で `default_model=null` を送る。
    - 残り option = chat/both のモデル。
  - `onchange` → `notebooksApi.update(id, {default_model})` → `currentNotebookStore` の `notebook.default_model` を更新 + トースト。
  - モデル一覧は `modelsStore`(`/api/models`)から取得。`currentNotebookStore.notebook.default_model` で現在値を選択表示。
- 検証(視覚): ノートでモデルを切替 → 永続化(リロード後も保持)、`既定` に戻すと `default_model=null`。

### (C) 埋め込みモデル選択 + 次元警告 + 再インデックス(最重量)

> **設計上の重要点**: 埋め込みは「選んだ瞬間に切り替わる」のではなく、**再インデックス操作を通じてのみ**有効になる(`embedding_model` と collection 次元は常に一体で動く)。これにより「dim 不一致で新規取り込みが落ちる」破綻状態を構造的に防ぐ。

- **次元検出**: `core/ollama/gateway.py`(または models_info)に `async probe_embedding_dim(gateway, model) -> int`。短文(例 `"x"`)を `embed` し `len(vector)` を返す。`/api/models` で embedding/both のモデルに `embedding_dim` を付与(失敗時 `null`)。プローブは結果をプロセス内キャッシュ。
- **現行 collection 次元**: `core/storage/vector_store.py VectorStore.collection_dim() -> int | None`(`get_collection(COLLECTION).config.params.vectors.size`、collection 無ければ `None`)を追加。
- **dim 動的化**: `apps/api/dependencies.py` の `_EMBEDDING_DIM=1024` 撤廃。`build_context` で:
  1. 既存 collection があればその次元を採用(`ensure_collection` は既存を尊重するため整合)。
  2. 無ければ `settings.json` の `ollama.embedding_dim`(無ければ既定 1024)を採用。
  - 起動時に Ollama を叩かない(落ちていても起動可能に保つ)。`embedding_dim` は再インデックス/初回取り込み時に `settings.json` へ確定保存。
- **切替(再インデックス)エンドポイント**: `POST /api/settings/embedding/switch`(body `{model: str}`)。
  1. `model` が embedding/both であることを検証(違反 400)。
  2. `new_dim = probe_embedding_dim(model)`。
  3. collection を再作成(drop → `create_collection(size=new_dim)`)。`VectorStore.recreate_collection(dim)` を追加。
  4. 全ノートブックの全チャンクを走査(`sources` → `list_chunks_for_source`)。各チャンク本文を `model` で再埋め込みし、元 payload(notebook_id/source_id/source_kind/page/heading_path/ord/start_ms/end_ms/speaker/channel)を保って `upsert`。
  5. 成功時: `cfg.ollama.embedding_model=model`、VectorStore dim を更新、`save_section(... "ollama" ...)` に `embedding_model`/`embedding_dim` を保存。3経路(pipeline/retrieval/recording_pipeline)が参照する `embedding_model` も更新が必要 → これらは `cfg.ollama.embedding_model` を起動時に値コピーしている。**結線方針**: 各サービスが実行時に最新 `embedding_model` を読むよう、`build_context` で渡す値を「getter / cfg 参照」に変更する(下記「横断方針」参照)。
  6. 進捗: `SseBroker` で `reindex_progress {done, total}` / `reindex_complete {model, dim}` / `reindex_error {message}` を配信。失敗時は collection を旧 dim で作り直すか、エラーを表面化して手動復旧を促す(MVP は「エラー表面化 + 再実行可能」)。
- **フロント**:
  - 設定 `section==='models'` の「埋め込みモデル」`<dd>` を `<select>`(embedding/both のみ)に変更。
  - 選択したモデルの `embedding_dim` が現行 collection 次元と異なる場合、インライン警告バナー:
    「選択したモデルは {new_dim} 次元です。現在のインデックスは {cur_dim} 次元(既存チャンクは {cur_embedding_model})。切り替えると **全ソースを再インデックス**します(数分かかる場合があります)。」
  - 「再インデックスして切替」ボタン → 確認 → `POST /settings/embedding/switch`。SSE 進捗をプログレス表示。完了でトースト + 設定再 `load()`。
  - 同次元の別モデル選択時は dim 警告は出さないが「再インデックス推奨(埋め込み空間が変わるため)」の情報注記を出し、同じ切替フローを使う。
- 検証(統合): fake embedder(次元可変)で switch → collection が新 dim で再作成され、全チャンクが再 upsert されること。dim 不一致警告が UI に出ること(視覚)。

## 5. スコープ確認(レビューで合意したい点)
1. **再インデックスエンジン((C) の本体)を本バッチに含めるか**。
   - 推奨: **含める**。埋め込み `<select>` が「選んでも実際には切り替わらない」飾りになるのを避けるため。ローカル個人利用かつチャンク本文は SQLite 永続なので全再埋め込みは現実的。
   - 代替(分割案): 本バッチは (A)+(B)+「(C) 分類/選択UI/次元警告まで(切替は警告のみで別 dim はブロック)」に絞り、再インデックスエンジンを次バッチへ。
2. **埋め込み `embedding_model` のサービス結線変更**(起動時値コピー → 実行時 cfg 参照)を許容するか(横断的だが小さい)。
3. **再インデックス中の失敗時の扱い**: MVP は「エラー表面化 + 再実行可能」。自動ロールバック(旧 dim 復元)は対象外でよいか。

## 6. 横断方針 / 非機能
- 新規ランタイム依存なし。分類は `/api/show` の `capabilities`(既存 `show()` が取得済み)+ 名前フォールバック。
- **embedding_model のサービス参照**: 現状 `build_context` で各サービスへ `embedding_model` を値で渡している。切替を再起動なしで反映するため、`IngestionPipeline`/`RetrievalService`/`RecordingPipeline` が実行時に `config.ollama.embedding_model` を読む形へ最小変更(deps に config 参照 or getter を持たせる)。LLM 既定(`default_model`)は元々 `chat.py` がリクエスト毎に `cfg.ollama.default_model` を読むため追加結線不要。
- LLM 既定の選択は保存後すぐ反映。埋め込みは再インデックス完了時に反映。
- 既存テストを壊さない。新規バックエンドはユニット/統合、GUI 変更は Playwright 実機検証ゲート(スクショ必須)。
- コミット trailer は付けない。

## 7. テスト方針(概要)
- ユニット: `classify_kind`(capabilities/フォールバック/both)、`probe_embedding_dim`(fake embedder)。
- 統合: `PUT /settings/ollama`(chat→200/embedding→400/永続化)、`POST /settings/embedding/switch`(collection 再作成 + 全チャンク再 upsert、永続化、進捗イベント)、`apply_overrides` の `ollama` 適用。
- 視覚(Playwright): 設定の既定LLM `<select>`、埋め込み `<select>`+次元警告バナー、ノート detail のモデルピッカー、切替後の永続化。

## 8. 対象外
- 群2 #3(保存先パス)、群3(#1 アクセラレータ / #9 リモート推論)。
- 再インデックスの自動ロールバック、増分(差分のみ)再インデックス、複数埋め込み collection の併存。
- リモート/API 経由モデル(#9 で扱う)。
