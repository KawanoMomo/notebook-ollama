# 設計仕様: チャット音声入力(Notebook Ollama)

- 日付: 2026-07-05(改訂: PTTキー設定・ハンズフリーモード追加)
- ステータス: 承認済み(ブレインストーミング完了)
- 対象: `apps/web` ChatInput + 設定画面 + `apps/api` 新規 STT ルーター

## 1. 目的

チャットの質問文をキーボードで打つ手間を減らすため、ChatInput に音声入力を追加する。
音声認識は既存の faster-whisper 基盤(録音ソース機能で導入済み)を再利用し、
完全ローカルで動作させる。

操作は 2 モード + 無効を設定画面で切替可能にする:

- **プッシュトゥトーク(既定)**: 設定したキー(既定: Space)を押している間だけ録音
- **常時有効(ハンズフリー)**: マイクを常時オンにし、発話区間ごとに自動で逐次テキスト化
- **無効**: マイクボタン非表示・キーフック無効

## 2. スコープ

### やること
- ChatInput へのマイクボタン追加(モード別の録音制御、認識テキストを textarea に追記)
- 音声変換 API `POST /api/stt/transcribe` の新設(既存 transcriber の薄いラッパー、ステートレス)
- 設定画面に「音声入力」セクション追加(モード 3 値 + PTT キー割当)、サーバー側に永続化
- プッシュトゥトーク: キー押下中のみ録音(hold-to-talk)、既定キーは Space
- ハンズフリー: ブラウザ側 VAD で発話区間を切り出し、区間ごとにバッチ変換を繰り返す
- recording extra 未導入環境でのグレースフルデグレード(503 + 導入ヒント)

### やらないこと(v1 非ゴール)
- サーバー側ストリーミング認識(WebSocket / 既存 LiveCaption の再利用)。ハンズフリーは
  ブラウザ側 VAD + バッチ POST の反復で実現し、サーバーはステートレスのまま保つ。
  認識精度・応答性が不足した場合の v2 候補として温存
- Web Speech API フォールバック
- 認識後の自動送信(誤認識のまま RAG 検索が走るリスクを避ける)
- 録音ソース機能との統合(チャット用音声は保存しない、使い捨て)
- 修飾キー組合せ(Ctrl+Space 等)の PTT キー割当(v1 は単一キーのみ)

## 3. 主要な意思決定(確定事項)

| # | 論点 | 決定 | 理由 |
|---|---|---|---|
| 1 | 認識エンジン | ローカル Whisper 再利用 | 完全ローカルの思想と一致。`app.state.transcriber` 共用で追加モデルロードなし |
| 2 | 操作スタイル | PTT(hold-to-talk)+ ハンズフリーの 2 モードを設定で切替 | 短い質問は PTT、長い口述や手が塞がる場面はハンズフリー |
| 3 | 取込経路 | ブラウザ側録音(getUserMedia + Web Audio) | セッション管理不要。会議録音実行中でもマイクデバイスが競合しない |
| 4 | 認識結果の扱い | textarea に追記のみ(自動送信しない) | 固有名詞・専門用語の誤認識を送信前に修正できる。Cmd/Ctrl+Enter で即送信可能 |
| 5 | PTT キー | 既定 Space、設定画面で単一キー(`KeyboardEvent.code`)に変更可能 | Claude デスクトップ等の慣行に合わせる。編集可能要素フォーカス中はキーを奪わない(下記) |
| 6 | ハンズフリー実装 | ブラウザ側 RMS ベース VAD + 発話区間ごとの WAV バッチ POST | サーバー変更ゼロで v1 API をそのまま反復利用。WS/セッション管理を持ち込まない |
| 7 | 設定の永続化 | 既存 `/api/settings`(core/config.py)に voice_input 系フィールドを追加 | 設定機構の新設不要。既存の設定画面・スキーマのパターンに乗る |

## 4. 全体フロー

### プッシュトゥトーク(既定)

```
[ChatInput / document キーフック]              [FastAPI]
 PTTキー押下(押している間)
   → getUserMedia + Web Audio で PCM 録音
 キー解放
   → クライアントで WAV 化し multipart POST ─→ POST /api/stt/transcribe
                                                ├ (必要なら ffmpeg で 16kHz mono WAV 化)
                                                ├ _get_transcriber().transcribe(language="ja")
                                                └ セグメント text 連結
 ← {text, duration_ms} ←───────────────────────┘
   → textarea 末尾に追記(既存文があれば空白を挟む)
```

- マイクボタンの**長押し**(mouse/touch)でも同じ動作(編集可能要素フォーカス中の代替手段)
- 120 秒に達したら自動停止して送信(クライアント側で実施。サーバーは長さチェックしない)

### 常時有効(ハンズフリー)

```
 マイクボタンクリック(または PTT キー単押し)でオン/オフをトグル
 オンの間:
   ブラウザ側 VAD(RMS しきい値 + ハングオーバー)が発話区間を検出
     - プリロール約 300ms / 無音約 800ms で区間確定 / 1 区間最大 30 秒で強制分割
   区間確定のたびに WAV 化 → POST /api/stt/transcribe → textarea に追記
   POST はクライアント側キューで直列化(応答順の入れ替わりによる追記順序乱れを防ぐ)
```

## 5. バックエンド API

### `POST /api/stt/transcribe`(新規)

- ルーター: `apps/api/routers/stt.py`(新規、薄い 1 ファイル)
- 入力: multipart form の音声ファイル(クライアント WAV 化を基本とし、webm/opus 等が
  来ても ffmpeg 経由で 16kHz mono WAV に正規化する)
- 処理:
  1. recording extra ガード — faster-whisper import 不可なら 503 + 導入ヒント
     (`recordings.py` の `_RECORDING_EXTRA_HINT` パターン踏襲)
  2. 一時ディレクトリに blob 保存
  3. 16kHz mono WAV でなければ ffmpeg subprocess で変換(`audio_export.py` と同じ
     呼び出しパターン)。ffmpeg 不在・変換失敗は 503/422
  4. `_get_transcriber(request)` で共有 transcriber を解決し
     `transcribe(wav_path, channel="mic", speaker_id="you", language="ja")`
  5. セグメントの `text` を連結して返す
- 出力: `{ "text": str, "duration_ms": int }`(認識結果が空なら `text=""`)
- 制限: アップロード上限 20MB(サーバー側で 413)
- モード・キーによらずこのエンドポイント 1 本(PTT もハンズフリーも同じ)
- `core/` の変更なし

### 設定フィールド(既存 `/api/settings` に追加)

| フィールド | 型 / 値 | 既定 |
|---|---|---|
| `voice_input_mode` | `"off" \| "push_to_talk" \| "hands_free"` | `"push_to_talk"` |
| `voice_input_ptt_key` | `KeyboardEvent.code` 文字列(単一キー) | `"Space"` |

- `core/config.py` の設定グループと `apps/api/schemas/settings.py` の
  Update/Response スキーマに同名で追加(`live_caption_default` 等の既存パターン踏襲)

## 6. UI

### ChatInput(`apps/web/src/lib/components/ChatInput.svelte`)

- マイクボタンは送信ボタン横の既存 `.row` 内に配置(縦方向に UI を肥大化させない)
- モード別挙動:
  - **PTT**: キー押下中またはボタン長押し中のみ録音中表示(赤・パルス + 経過秒)。
    解放で変換中(Spinner)→ 追記
  - **ハンズフリー**: クリックでトグル。オン中は常時パルス表示 + 変換中は小 Spinner 併記
  - **無効**: ボタン非表示・キーフックなし
- PTT キーフックは document レベルで登録し、**フォーカスが編集可能要素
  (textarea / input / contenteditable)にある間は発火させない**(Space は通常の空白入力。
  代替はボタン長押し)。keydown リピートは無視し、keyup で確定
- 録音中にストリーミング応答が始まっても録音は継続可(挿入先は textarea のみで、
  送信ガードは既存ロジックのまま)
- recording extra 未導入でもボタンは表示(押下時に 503 ヒントを Toast 表示)

### 設定画面(`apps/web/src/routes/settings`)

- 「音声入力」セクションを新設(既存セクション構成のパターン踏襲):
  - モード選択: 無効 / プッシュトゥトーク / 常時有効(ハンズフリー)のラジオまたはセレクト
  - PTT キー割当: 「キーを押して設定」方式(フォーカス後、次の keydown の `code` を採用、
    Esc でキャンセル)。現在の割当キーを表示
  - モードが PTT 以外のときキー割当 UI は無効表示(グレーアウト)

## 7. エラー処理

| ケース | 挙動 |
|---|---|
| マイク権限拒否 / デバイスなし | Toast「マイクへのアクセスが拒否されました」(ハンズフリー中なら自動オフ) |
| recording extra 未導入(503) | サーバーのヒント文言を Toast 表示(`uv sync --extra recording` 案内) |
| ffmpeg 不在(503)/ 変換失敗(422) | Toast でエラー通知、textarea 変更なし |
| 無音・認識結果空 | PTT: Toast「音声を認識できませんでした」。ハンズフリー: 無通知でスキップ(常態のため) |
| サイズ超過(413) | Toast で上限を案内 |
| PTT 録音 120 秒到達 | クライアントが自動停止し通常フローで変換(エラーではない) |
| ハンズフリー中の変換失敗 3 連続 | 自動でオフに切替 + Toast(無限失敗ループ防止) |
| 設定の保存失敗 | 既存設定画面のエラー表示パターンに従う |

## 8. テスト & 検証ゲート

### テスト
- 統合(`tests/integration/test_api/`):
  - `transcriber_factory` 注入の fake transcriber で正常系 — text 連結と duration_ms を検証
    — 既存 `test_recordings_api.py` パターン
  - extra 未導入時の 503 — 既存 `test_recording_extras_optional.py` パターン
  - 空認識(セグメント 0 件)で `text=""`
  - サイズ超過 413
  - 設定 roundtrip: `voice_input_mode` / `voice_input_ptt_key` の GET/PUT 永続化と
    不正値(未知のモード・空キー)の 422
- 単体: ffmpeg コマンド組み立て・WAV 判定を関数に切る場合はその関数のみ対象。
  ブラウザ側 VAD(RMS 判定・ハングオーバー)は純粋関数に切り出し、フロントの
  テスト基盤があれば単体対象、なければ evaluator の実機検証でカバー

### 検証ゲート(必須)
- GUI 変更のため、自動テスト GREEN だけでは PASS にしない。
  evaluator による実機スクリーンショット検証を PASS 条件に含める:
  - マイクボタン表示(各モード)/ 録音中状態 / 認識テキスト挿入
  - 設定画面の音声入力セクション(モード切替・キー割当 UI)
  - マイク実音声は使えないため、Chromium の fake デバイス
    (`--use-fake-device-for-media-stream` + `--use-fake-ui-for-media-stream`)または
    UI 状態・エラーパスの検証で代替する(検証手段は plan で確定)

## 9. リスク / 留意点

- **初回レイテンシ**: transcriber が未ロードの場合、初回リクエストで WhisperModel の
  ロード(数秒〜十数秒)が走る。録音ソース機能と共用キャッシュなので 2 回目以降は即時
- **同時実行**: Transcriber は `_serial_lock` で直列化済み。会議録音のライブ字幕と
  チャット音声入力が同時に走ると後着が待たされる(壊れはしない)。ハンズフリーは
  発話区間ごとに POST するため、ライブ字幕との同時利用では待ち時間が体感されやすい
- **ブラウザ側 VAD の精度**: RMS ベースの簡易 VAD は騒音環境で区切りを誤る可能性。
  しきい値・ハングオーバーは定数として切り出し調整可能にする(v1 では設定 UI 非公開)。
  精度不足なら v2 でサーバー側 webrtcvad(既存資産)への移行を検討
- **Space キーの競合**: 既定キーが Space のため、編集可能要素フォーカス中は
  キーフックを発火させない設計が必須(§6)。それでもページスクロール等の既定動作とは
  競合しうるため、PTT 発火時は `preventDefault()` する
- **ブラウザ差**: クライアント WAV 化を基本とするためコンテナ差の影響は小さいが、
  検証は Chrome を一次対象とする
- **HTTPS 制約**: getUserMedia は secure context 必須。localhost は平文 HTTP でも
  動作するため、本アプリの利用形態(ローカル)では問題なし
