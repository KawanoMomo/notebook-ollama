# 開発者モード 設計書

- Status: Draft
- Author: KawanoMomo
- Date: 2026-07-02
- Related: `docs/specs/notebook-ollama-design.md`

## 1. 概要

フロントエンドで開発・調査するときに、サーバー側で起きていること（アプリログ、
Ollama へのリクエスト／レスポンス、Ollama サーバ本体のログ、SSE イベント）が
ブラウザから見えない。これを見えるようにする **開発者モード** を追加する。

一般ユーザーには一切露出しないよう、次の二段階で隠す。

1. 設定画面の「開発者モード」トグルを ON にする（サーバ側 settings_store に永続化）。
   デフォルト OFF。
2. サイドバー上部のアプリロゴを **3 秒以内に 7 回連続クリック** すると
   Dev パネル（フローティングオーバーレイ）が開く。

いずれか一方だけでは Dev パネルは開かない。設定 OFF 中はロゴ連打も無反応、
`/api/dev/*` は 403 を返す。

## 2. 用語

| 用語 | 意味 |
|---|---|
| DevLogRing | プロセス内 singleton のリングバッファ。バイト容量指定。 |
| DevBroker | Dev 用の pub/sub。既存 `SseBroker` と同型。 |
| DevSinkHandler | structlog processor と stdlib logging.Handler の両顔を持つ吸い口。 |
| Dev パネル | ブラウザに浮かぶフローティングオーバーレイ UI。 |
| seq | DevLogRing 内エントリに採番される単調増加 ID。リング寿命中一意。 |

## 3. 要件

### 3.1 機能要件

- FR-1: 設定画面に「開発者モード」トグルを追加。サーバ側 `settings_store` に永続化。
- FR-2: 設定 ON かつサイドバーロゴ **7 回 / 3 秒以内** クリックで Dev パネルを開く。
- FR-3: Dev パネルは次の 4 種のログを表示できる。
  - App（structlog INFO+、HTTP アクセス、例外を含む）
  - Ollama（NotebookOllama → ollama への request / stream chunk / response、payload 全文）
  - Server（`%LOCALAPPDATA%\Ollama\server.log` の tail）
  - Events（既存 `SseBroker.publish` の mirror）
- FR-4: ログはメモリリングで保持。容量はバイト単位、超過時は古い側から drop。
- FR-5: 容量は設定画面で変更できる。デフォルト 20 MB、上限 200 MB、下限 1 MB。
- FR-6: 収集は設定 ON にした瞬間から開始する。再起動でリングは初期化される（永続化しない）。
- FR-7: Dev パネル UI は次を満たす。
  - フローティングオーバーレイ（ドラッグ移動、右下リサイズ、4 スナップ：右半／下半／最大化／既定）
  - タブ: App / Ollama / Server / Events / System
  - 1 行サマリ [level | time | source | msg] ＋ クリックで詳細 JSON 展開
  - フィルタ: level チェックボックス ＋ source 選択 ＋ テキスト検索
  - **上下往復スクロール**: 上へスクロールすると過去を range fetch、下端に戻ると SSE 追従。
  - 「⏸ 追従停止 / ▶ 最新へ」バッジで追従状態を明示
  - NDJSON エクスポート、Clear（サーバリングごと初期化）、Esc と × で閉じる
  - 位置・サイズを localStorage に保存し再オープン時に復元
- FR-8: 「開発者モード使用中」を示す視覚マーカーは表示しない。
- FR-9: `/api/dev/*` および Dev SSE は **設定 ON かつクライアント IP が `127.0.0.1` または `::1`** の
  AND 条件を満たすときだけ 200 を返し、それ以外は一律 403。

### 3.2 非機能要件

- NFR-1: 設定 OFF 中の本流レイテンシ増加は「enabled チェック 1 回」のオーダに収める。
- NFR-2: Dev 側で例外が発生しても本流の処理を止めない（例外は握り潰し、標準 logger に警告）。
- NFR-3: X-Forwarded-For は信頼しない（`request.client.host` のみ参照）。
- NFR-4: `ollama serve` のログ tail は Dev パネルの subscriber が 1 人以上いるときだけ動く。
- NFR-5: リングは並行 push に対して安全（threading.Lock）。
- NFR-6: リングのバイト計上は「push 時に確定」する（=読み出し時の再計算をしない）。

### 3.3 スコープ外

- 再起動を跨いだログ永続化（ファイル出力）
- LAN / リバースプロキシ越しでの Dev パネル利用
- MCP 経由での Dev ログ露出
- ユーザーごとのアクセス制御（個人ローカルツール前提）
- 「開発者モード ON」の視覚マーカー
- Ollama serve のログ以外の外部プロセスログ収集

## 4. アーキテクチャ概観

```
┌────────────────────────── Browser (SvelteKit) ──────────────────────────┐
│  Sidebar Logo ──7 clicks/3s──► hiddenCmd store ─┐                       │
│  /settings  ──toggle/容量変更────► /api/settings─┼─► DevPanel (overlay)  │
│                                                  │   ├ tabs             │
│                                                  │   │  App|Ollama|     │
│                                                  │   │  Server|Events|  │
│                                                  │   │  System          │
│                                                  │   ├ filter/export    │
│                                                  └─► EventSource        │
│                                                      /api/dev/stream    │
└───────────────────────────────────┬─────────────────────────────────────┘
                                    │ (SSE, localhost only)
┌───────────────────────────────────▼─────────────────────────────────────┐
│  FastAPI (apps/api)                                                     │
│                                                                         │
│  routers/dev.py ──guard(setting ON & local IP)                          │
│    ├ GET  /api/dev/stream?since_seq=                                    │
│    ├ GET  /api/dev/range?before_seq=&after_seq=&limit=&order=           │
│    ├ GET  /api/dev/stats                                                │
│    ├ POST /api/dev/clear                                                │
│    ├ GET  /api/dev/system                                               │
│    └ GET  /api/dev/export.ndjson?before_seq=&after_seq=                 │
│                                                                         │
│  routers/settings.py                                                    │
│    └ dev_mode_enabled : bool                                           │
│       dev_log_capacity_bytes : int                                      │
└───────────────────────────────────┬─────────────────────────────────────┘
                                    │
┌───────────────────────────────────▼─────────────────────────────────────┐
│  core/dev_logs/                                                         │
│    ├ ring.py     : DevLogRing (singleton, byte cap, seq)                │
│    ├ sink.py     : DevSinkHandler (structlog processor + logging)       │
│    ├ broker.py   : DevBroker (SSE pub/sub with since_seq)               │
│    └ tail.py     : OllamaServerLogTail (subscriber>0 のみ起動)         │
│                                                                         │
│  core/logging.py        --add--> DevSinkHandler を attach               │
│  core/ollama/client.py  --wrap-> _emit_dev(req/chunk/resp)              │
│  apps/api/sse.py        --hook-> SseBroker.publish に mirror            │
└─────────────────────────────────────────────────────────────────────────┘
                       ▲
                       │ subscriber>0 のときだけ tail
            %LOCALAPPDATA%\Ollama\server.log
```

## 5. アクセス制御

### 5.1 二段階

| 段階 | 実装場所 | 判定 |
|---|---|---|
| A. 設定トグル | 設定画面 → PUT `/api/settings` → `settings_store` | `dev_mode_enabled: bool` |
| B. 隠しコマンド | サイドバー上部のアプリロゴ | 3 秒以内に 7 クリック |

- 段階 A は BE 永続化。ブラウザを跨いで一貫。
- 段階 B は FE のみ。localStorage に `unlocked=true` を保存。
- 段階 A が OFF のとき、段階 B のカウントは常にリセットされる（=無反応）。
- 段階 A を OFF に戻すと、開いていた Dev パネルは自動で閉じ、`unlocked` は false に戻る。

### 5.2 API ガード

```python
def guard_dev_request(request: Request) -> None:
    ctx = request.app.state.ctx
    if not ctx.config.dev_mode_enabled:
        raise AppError(ErrorCode.DEV_UNAUTHORIZED, "developer mode is disabled")
    host = request.client.host if request.client else None
    if host not in ("127.0.0.1", "::1"):
        raise AppError(ErrorCode.DEV_UNAUTHORIZED, "developer mode is disabled")
```

- **X-Forwarded-For は読まない**（偽装耐性）。
- OFF と LAN 越しを外形上区別しない（一律 403）。
- 例外コード `dev.unauthorized` を新規追加。

## 6. 収集対象

| Source | 採取点 | 採取物 |
|---|---|---|
| app | `core/logging.py` の structlog processor + logging.Handler | INFO+、HTTP アクセス、例外 |
| ollama | `core/ollama/client.py` の各メソッド | request payload / stream chunk / response、model / options / latency / token 数 |
| server | `OllamaServerLogTail` | `%LOCALAPPDATA%\Ollama\server.log` の追記行 |
| events | `apps/api/sse.py` の `SseBroker.publish` mirror | topic / payload |

いずれの source も、`DevLogRing.disabled` 時は **1 回の enabled チェックだけで return** する。

## 7. リングバッファ層 — 端子設計

「上下に往復しながら読む」運用を前提とし、単なる snapshot ではなく **seq 指定の
範囲読み** ができる端子を持つ。

### 7.1 エントリ

```python
class DevLogEntry(TypedDict):
    seq:     int
    ts:      str
    level:   Literal["debug", "info", "warn", "error"]
    source:  Literal["app", "ollama", "server", "events", "meta"]
    msg:     str
    payload: dict
    size:    int
```

`size` は push 内で `len(json.dumps(entry_without_size).encode("utf-8"))` として確定。

### 7.2 DevLogRing 公開 IF

```python
class DevLogRing:
    # 書き込み
    def push(self, entry_without_seq: dict) -> int: ...

    # 範囲読み
    def read(
        self,
        *,
        after_seq:  int | None = None,   # 排他 (> after_seq)
        before_seq: int | None = None,   # 排他 (< before_seq)
        limit:      int = 500,
        order:      Literal["asc", "desc"] = "asc",
    ) -> ReadResult: ...

    # 概形
    @property
    def oldest_seq(self) -> int
    @property
    def latest_seq(self) -> int
    @property
    def next_seq(self) -> int
    @property
    def stats(self) -> dict

    # ライフサイクル
    def enable(self, capacity_bytes: int) -> None
    def disable(self) -> None
    def resize(self, capacity_bytes: int) -> None
    def clear(self) -> None   # entries だけ消去、next_seq は保持
```

### 7.3 ReadResult

```python
@dataclass
class ReadResult:
    entries:    list[DevLogEntry]   # order に従って並ぶ
    first_seq:  int | None
    last_seq:   int | None
    gap_before: bool                # 要求範囲の古い側に「失われた範囲」があるか
    gap_after:  bool                # 要求範囲の新しい側に「失われた範囲」があるか
    oldest_seq: int
    latest_seq: int
```

FE はこの gap フラグを行間に「⚠ ここから前は失われています」と描画する。

### 7.4 不変条件

| # | 内容 |
|---|---|
| I1 | 各 entry は単調増加の `seq` を持つ。リング寿命中に重複しない |
| I2 | drop によって `oldest_seq` が飛んでも、生存 entries の seq は強単調 |
| I3 | `clear()` は entries を消すが `next_seq` は保持する（=巻き戻らない） |
| I4 | `resize(new_cap)` で `new_cap < bytes` のときは即時に古い側から drop |
| I5 | `disable()` 後の `push()` は 0 を返す no-op。`stats` も進めない |
| I6 | 読み書きは threading.Lock で直列化、read は snapshot 後にロックを解放 |
| I7 | `next_seq` はプロセス寿命の中で単調（disable→enable でリセットしない） |

### 7.5 DevBroker

```python
class DevBroker:
    def subscribe(self, *, since_seq: int | None = None) -> Subscription: ...
    def unsubscribe(self, sub: Subscription) -> None: ...
    async def publish(self, entry: DevLogEntry) -> None: ...

    # 収集オンオフのフック
    def on_first_sub(self, cb: Callable[[], None]) -> None
    def on_last_unsub(self, cb: Callable[[], None]) -> None
```

- `since_seq` が `ring.oldest_seq` より古い場合、購読開始直後に
  `{type:"gap", lost_until: ring.oldest_seq}` を 1 件送り、その後
  `ring.read(after_seq=ring.oldest_seq - 1)` で追いついてからリアルタイム配信に合流。
- slow consumer 検知（queue が閾値超）: 該当購読者にだけ
  `{type:"gap", lost_until: ring.latest_seq}` を送って queue を flush し、以後のみ再開。
- `on_first_sub / on_last_unsub` は `OllamaServerLogTail.start / stop` を発火するために使う。

## 8. 計装点

### 8.1 DevSinkHandler

- structlog processor と `logging.Handler` の両方から呼ばれる薄い口。
- 先頭で `ring.disabled` なら即 return。
- entry 化 → `ring.push()` → `broker.publish()` の順。
- 内部 try/except で例外を握り潰し、自分自身に対しては push しない
  （`dev_logs` ロガーは Handler を attach しない → 無限ループ防止）。

### 8.2 OllamaClient ラッパ

`core/ollama/client.py` の各メソッドで、下記 3 点を発行する。

```python
async def chat_stream(...):
    _emit_dev({"source": "ollama", "phase": "req",
               "model": model, "options": options, "messages": messages})
    try:
        async for chunk in ...:
            _emit_dev({"source": "ollama", "phase": "chunk", "text": chunk_text})
            yield chunk_text
        _emit_dev({"source": "ollama", "phase": "resp",
                   "latency_ms": ..., "tokens": ...})
    except Exception as exc:
        _emit_dev({"source": "ollama", "phase": "error", "detail": str(exc)})
        raise
```

- `_emit_dev` は try/except で保護。Dev 側が壊れても chat_stream は継続する。
- payload は全文をそのまま格納する（マスキングしない）。

### 8.3 SseBroker mirror

`apps/api/sse.py` の `SseBroker.publish` を decorator で ラップし、
`{"source":"events", "topic": topic, "payload": payload}` を DevRing に流す。

### 8.4 OllamaServerLogTail

- 起動: `DevBroker.on_first_sub` で `start()`。
- 停止: `DevBroker.on_last_unsub` で `stop()`。
- 対象パス: `os.environ.get("LOCALAPPDATA") / "Ollama" / "server.log"`。
- 存在しない/権限なし: `{source:"server", level:"warn", msg:"server.log not found", path:...}`
  を 1 件だけ push し、以降は no-op。
- ローテーション検知: `os.stat` で `st_ino` / `st_size` を周期監視。
  サイズが減ったら reopen し、`{source:"server", level:"info", msg:"rotated, reopened"}` を 1 件 push。

## 9. API

すべて `guard_dev_request` を先頭で通す。エラーは `AppError(dev.unauthorized)` → 403。

| Method | Path | 概要 |
|---|---|---|
| GET  | `/api/dev/stream?since_seq=` | SSE。`since_seq` 以降を追いつかせてリアルタイム配信 |
| GET  | `/api/dev/range?before_seq=&after_seq=&limit=&order=` | 範囲読み |
| GET  | `/api/dev/stats` | `{oldest_seq, latest_seq, next_seq, entries, bytes, capacity_bytes, dropped_total}` |
| POST | `/api/dev/clear` | ring.clear()。`next_seq` は据え置き |
| GET  | `/api/dev/system` | `{ollama_models, git_rev, config_snapshot}` |
| GET  | `/api/dev/export.ndjson?before_seq=&after_seq=` | NDJSON ダウンロード（省略時は全件） |

### 9.1 SSE ペイロード

`event: entry` / `data: <DevLogEntry JSON>` を基本。

制御用イベント:
- `event: gap` / `data: {"lost_until": <seq>}` — 過去に失われた範囲があることを FE に通知。
- `event: meta` / `data: {"type":"drop", "count": <int>}` — 直近 1 秒間の drop 件数を throttle 通知。
- `event: shutdown` / `data: {}` — 設定 OFF 遷移時、購読者に閉じることを促す。

### 9.2 settings スキーマ拡張

```python
class SettingsIn(BaseModel):
    ...
    dev_mode_enabled:       bool | None = None
    dev_log_capacity_bytes: int  | None = None   # 1MB..200MB でクランプ
```

- クランプ結果は GET `/api/settings` で観測可能。範囲外は 400 ではなく採用値で応答。
- `AppConfig.apply_overrides` の延長で、`DevLogRing.resize` と
  `DevSinkHandler.install/uninstall` を呼ぶ。

## 10. Frontend

### 10.1 hidden command store

`apps/web/src/lib/stores/devmode.ts`

```ts
export const devmode = writable({
    enabled:   boolean,   // /api/settings 由来
    unlocked:  boolean,   // localStorage 保存
    panelOpen: boolean,
});

export function registerLogoClick(): void {
    // enabled=false のときは何もしない。
    // 直近 3 秒で 7 回に達したら unlocked=true, panelOpen=true。
}
```

- 段階 A の enabled が false になった瞬間、`unlocked=false`、`panelOpen=false` に強制リセット、
  localStorage の該当キーも削除する。
- `EventSource('/api/dev/stream')` が 403 を返した瞬間も同様にリセット。

### 10.2 DevPanel

`apps/web/src/lib/components/DevPanel.svelte`

- ドラッグ移動、右下リサイズ、4 スナップ（右半／下半／最大／既定）。
- 位置・サイズ・スナップ状態を localStorage に保存。
- タブ: App / Ollama / Server / Events / System。stream は 1 本維持し、タブは同じ entry 列を
  FE 側でフィルタするだけ。
- 各行 [level | time | source | msg]。クリックで詳細 JSON を展開。
- フィルタ: level チェックボックス、source ドロップダウン、テキスト検索。
- **上下往復スクロール**:
  - 下端付近では `follow=true`（新着で自動スクロール）。
  - 上方向にスクロールされた瞬間 `follow=false`（追従停止バッジ）。
  - 「▶ 最新へ」ボタンで `EventSource` を再接続して下端ジャンプ。
  - 上端到達で `range?before_seq=first_seq&order=desc&limit=500` を発火。
  - `gap_before / gap_after` に応じてセパレータ行「⚠ ここから前は失われています（容量超過）」を描画。
- ヘッダに `stats` バッジ（`entries / bytes / dropped_total`）。
- Clear ボタン: 「サーバ側も含めて消去します。よろしいですか?」の確認モーダル → POST `/api/dev/clear`。
- Export ボタン: 現在のフィルタ範囲で GET `/api/dev/export.ndjson` を開く。
- 閉じる: `×` と `Esc`。

### 10.3 設定画面

`apps/web/src/routes/settings` に既存の他項目と同じ体裁で 2 項目を追加。

- 「開発者モード」トグル
- 「開発ログ保持容量 (MB)」数値入力／スライダ（1〜200、既定 20）

いずれも PUT `/api/settings` に一本化。

## 11. データフロー

### S1. 起動 〜 設定 OFF（一般ユーザ）

- lifespan で `configure_logging()` → `DevLogRing()` `DevBroker()` `DevSinkHandler.install()`。
- `settings_store.apply_overrides` で `dev_mode_enabled=False` を確認 → ring は disabled のまま。
- structlog / OllamaClient / SseBroker mirror は enabled チェック 1 発で return。

### S2. 設定 ON にした瞬間

- PUT `/api/settings { dev_mode_enabled: true, dev_log_capacity_bytes: 20MB }`。
- settings 側で `DevLogRing.enable(20MB)`。以降 `push()` は有効。
- tail はまだ subscriber=0 なので未起動。

### S3. 隠しコマンド → Dev パネル オープン

- ロゴ 7 連打成功 → `panelOpen=true`。
- FE mount → `EventSource('/api/dev/stream?since_seq=<localStorage 最後の seq>?)`。
- BE guard 通過 → `broker.subscribe(since_seq=...)` → subscriber 0→1 で
  `OllamaServerLogTail.start()`。
- 初回に `ring.read()` を snapshot として返し、以降 broker からの publish を SSE 化。

### S4. 実トラフィックが Dev パネルに流れる経路

- structlog `logger.info(...)` → DevSinkHandler → `ring.push` + `broker.publish` → SSE → FE。
- OllamaClient.chat_stream → `_emit_dev` を req / chunk / resp / error で発火。
- SseBroker.publish decorator → `source="events"` として発火。
- OllamaServerLogTail 追記検知 → `source="server"` として発火。

### S5. 設定変更・OFF 遷移

- 容量変更: `DevLogRing.resize(new_cap)`。縮小時は古い側から drop、`stats` 更新。
- OFF 遷移: `ring.disable()` → `broker.publish({type:"shutdown"})` → `broker.disconnect_all()` →
  tail 停止。FE は `shutdown` 受信で `EventSource.close()`、`unlocked=false`、`panelOpen=false`、
  localStorage 該当キー削除。

## 12. 不変条件（横断）

| # | 内容 | 守る場所 |
|---|---|---|
| I8 | 設定 OFF のとき本流のレイテンシ増加は enabled チェック 1 回 | DevSinkHandler / _emit_dev / mirror の各先頭 |
| I9 | Dev 側で例外が出ても本流の処理は止まらない | 各 emit 点の try/except、失敗は標準 logger.warning のみ |
| I10 | 容量超過時は古い側 drop、push 自体は成功する | `DevLogRing.push` 内部 |
| I11 | `/api/dev/*` と `/api/dev/stream` は `dev_mode_enabled && localhost` の AND を **全エンドポイントの先頭** で評価する | `guard_dev_request` を Depends 共有 |
| I12 | ollama serve tail は subscriber > 0 のときだけ走る | `DevBroker.on_first_sub / on_last_unsub` |

I1〜I7 はリング内不変条件（§7.4）。

## 13. エラーハンドリング

| # | ケース | 動作 |
|---|---|---|
| E1 | Dev 側 emit 失敗（serialize 不能、ring 破損） | try/except で握り潰し。`logging.getLogger("dev_logs").warning(...)` を 1 行。本流はそのまま |
| E2 | リング容量超過 | 古い側 drop、`dropped_total` を進める。1 秒 throttle で `meta:{type:"drop", count}` を配信 |
| E3 | server.log が存在しない/権限なし | `{source:"server", level:"warn", msg:"server.log not found"}` を 1 件 push、`start()` を no-op で抜ける |
| E4 | server.log ローテーション / truncate | reopen し、`{source:"server", level:"info", msg:"rotated, reopened"}` を 1 件 push |
| E5 | SSE の遅い読み手 | 該当購読者にだけ `gap:{lost_until:<latest_seq>}` を送って queue を flush、以降のみ再開 |
| E6 | guard 失敗（OFF / LAN） | 一律 `403` `{"error":{"code":"dev.unauthorized","message":"developer mode is disabled"}}` |
| E7 | 設定値の範囲外 | 1MB〜200MB でクランプ、GET で採用値を返す。FE はトーストで通知 |
| E8 | ON→OFF 遷移中のレース | `ring.disable() → publish(shutdown) → disconnect_all()` の順で直列化 |
| E9 | 起動タイミング | `configure_logging()` は lifespan 先頭で実行（既存主義）。router 登録前に Handler を attach |

## 14. テスト戦略

### tests/unit

- `DevLogRing`
  - push 連続で `seq` がギャップなく増える
  - drop 発生時、生存 entries の `seq` は強単調
  - `read(after_seq=X)` で X が drop 済のとき `gap_before=True`
  - `read(before_seq=X, order=desc, limit=N)` で逆順、ページング 2 回で `oldest_seq` に到達
  - `clear()` 後の push は `next_seq` から続く（巻き戻らない）
  - `resize` で縮小すると即時 drop、拡大しても既存 entries は増えない
  - `disable()` 後の push は 0 を返す。`stats` も進めない
  - 並行 push 100 スレッド × 1000 件で総バイトが容量を超えない
- `DevSinkHandler`
  - `ring.disabled` なら `ring.push` を呼ばない
  - structlog の構造化キーを保ったまま entry 化される
  - emit 失敗時に自分自身にログを積まない
- `guard_dev_request`
  - `dev_mode_enabled=False` で 403
  - LAN IP（192.168.x.x）で 403
  - localhost + enabled で通過
  - X-Forwarded-For が付いていても IP 判定は `request.client.host` のまま

### tests/integration

- ライフサイクル
  - 設定 ON → 10 件 push → snapshot に 10 件
  - 容量 1KB に resize → 古いものから消える
  - 設定 OFF → `EventSource` が `shutdown` を受け取って閉じる
- `/api/dev/stream`
  - 接続 → 最初のメッセージが snapshot
  - 追加 push が SSE で届く
  - 切断で購読が外れる
  - `since_seq` が古すぎるとき先頭に `gap` イベントが 1 件
- `/api/dev/range`
  - `before_seq=&order=desc` ページング、`gap_before` フラグの整合
- mirror
  - SseBroker.publish → Dev ring に `source="events"` で入っている
- Ollama wrapper（fake ollama）
  - chat_stream 成功 → `phase=req → chunk* → resp`
  - Ollama エラー → `phase=error`、本流は既存通り `AppError`
- Server tail
  - 一時ディレクトリに `server.log` を置き、追記 → ring に流入
  - 削除 → 再作成 → reopen エントリ
  - 存在しないパス → 「not found」1 件 push で以降 no-op

### FE (Playwright)

- 設定 OFF でロゴ 7 連打 → 何も起きない（DOM に DevPanel 要素が出ない）
- 設定 ON + 7 連打 → DevPanel が出る、Esc で閉じる
- 位置とサイズが localStorage に保存され、再オープン時に復元
- タブ切替で stream は再接続されない（1 EventSource 維持）
- 上スクロール → 追従停止 → 過去 fetch → gap セパレータ表示
- 「▶ 最新へ」→ 再接続して下端ジャンプ
- NDJSON ダウンロードで `Content-Disposition: attachment` を確認
- 設定 OFF に戻すと DevPanel が閉じ、ロゴ 7 連打が無効化される

### tests/mcp

- 変更なし。Dev router は MCP には露出しない。

### 手動 / 受け入れシナリオ

1. 一般ユーザ確認: 設定 OFF で「ロゴ 7 連打」 → 何も起こらない。ヘッダに視覚マーカーもない。
2. 開発者確認: 設定 ON → 7 連打 → DevPanel → チャット実行 → App / Ollama / Events が流れる。
   Server タブに ollama serve のロード行が出る。
3. LAN 越しに hostname:8765 で /api/dev/stream → 403。
4. 容量 200MB を超える値を設定 → クランプ 200MB。
5. 容量 1MB に絞って大量チャット → `drops: N` バッジが表示される。
6. Dev パネルを開いたまま上に遡り、gap セパレータが表示される。
7. パネルを閉じて再オープン → 「閉じた地点に戻る／最新を見る」を選択できる。

## 15. オープン事項 / 将来の拡張

- 「閉じた地点に戻る」の記憶方式（`last_seq_on_screen`）は MVP に含めるかを別途決める。
- Dev パネル内での「ピン留め行」機能（重要イベントを固定表示）は将来検討。
- Ollama 以外の外部プロセスログ（例: Qdrant）を対象化するかは需要が出てから。
- 認証付きで LAN からも見たいユースケースが出た場合は `X-Dev-Token` 方式を後付け検討。
