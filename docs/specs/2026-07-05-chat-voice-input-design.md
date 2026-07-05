# 設計仕様: チャット音声入力(Notebook Ollama)

- 日付: 2026-07-05
- ステータス: 承認済み(ブレインストーミング完了)
- 対象: `apps/web` ChatInput + `apps/api` 新規 STT ルーター

## 1. 目的

チャットの質問文をキーボードで打つ手間を減らすため、ChatInput にプッシュトゥトーク方式の
音声入力を追加する。音声認識は既存の faster-whisper 基盤(録音ソース機能で導入済み)を
再利用し、完全ローカルで動作させる。

## 2. スコープ

### やること
- ChatInput へのマイクボタン追加(録音 → 停止 → 認識テキストを textarea に追記)
- 音声変換 API `POST /api/stt/transcribe` の新設(既存 transcriber の薄いラッパー)
- recording extra 未導入環境でのグレースフルデグレード(503 + 導入ヒント)

### やらないこと(v1 非ゴール)
- ライブディクテーション(話しながら逐次テキスト化)。既存 LiveCaption の再利用は
  将来の拡張として温存するが、v1 はバッチ 1 発のみ
- Web Speech API フォールバック
- 認識後の自動送信(誤認識のまま RAG 検索が走るリスクを避ける)
- 録音ソース機能との録音の統合(チャット用音声は保存しない、使い捨て)

## 3. 主要な意思決定(確定事項)

| # | 論点 | 決定 | 理由 |
|---|---|---|---|
| 1 | 認識エンジン | ローカル Whisper 再利用 | 完全ローカルの思想と一致。`app.state.transcriber` 共用で追加モデルロードなし |
| 2 | 操作スタイル | プッシュトゥトーク(押す→話す→押す) | ステートレス POST 1 本で済み、短い質問文に十分な応答性(停止後 1〜3 秒) |
| 3 | 取込経路 | ブラウザ側録音(getUserMedia + MediaRecorder) | セッション管理不要。会議録音実行中でもマイクデバイスが競合しない |
| 4 | 認識結果の扱い | textarea に追記のみ(自動送信しない) | 固有名詞・専門用語の誤認識を送信前に修正できる。Cmd/Ctrl+Enter で即送信可能 |

## 4. 全体フロー

```
[ChatInput.svelte]                         [FastAPI]
 マイクボタン押下
   → getUserMedia + MediaRecorder 録音開始
     (ボタンは赤・パルス、経過秒表示)
 再押下で停止
   → audio blob (webm/opus) を multipart POST ─→ POST /api/stt/transcribe
                                                   ├ 一時ファイル保存
                                                   ├ ffmpeg で 16kHz mono WAV 化
                                                   ├ _get_transcriber().transcribe(language="ja")
                                                   └ セグメント text 連結
 ← {text, duration_ms} ←──────────────────────────┘
   → textarea 末尾に追記(既存文があれば空白を挟む)
   → ユーザーが確認・修正して送信(既存フロー)
```

## 5. バックエンド API(新規)

### `POST /api/stt/transcribe`

- ルーター: `apps/api/routers/stt.py`(新規、薄い 1 ファイル)
- 入力: multipart form の音声ファイル(MediaRecorder 既定の webm/opus を想定。
  コンテナは ffmpeg 任せなので ogg/mp4 でも通る)
- 処理:
  1. recording extra ガード — faster-whisper import 不可なら 503 + 導入ヒント
     (`recordings.py` の `_RECORDING_EXTRA_HINT` パターン踏襲)
  2. 一時ディレクトリに blob 保存
  3. ffmpeg subprocess で 16kHz mono WAV に変換(`audio_export.py` と同じ呼び出しパターン)。
     ffmpeg 不在・変換失敗は 503/422
  4. `_get_transcriber(request)` で共有 transcriber を解決し `transcribe(wav_path, channel="mic", speaker_id="you", language="ja")`
  5. セグメントの `text` を連結して返す
- 出力: `{ "text": str, "duration_ms": int }`(認識結果が空なら `text=""`)
- 制限: アップロード上限 20MB(サーバー側で 413)。音声長上限 120 秒はクライアント側で
  実施(録音が 120 秒に達したら自動停止して送信。サーバーでは長さチェックしない)
- `core/` の変更なし。認識ロジックはすべて既存 Transcriber を使用

## 6. UI(`apps/web/src/lib/components/ChatInput.svelte`)

- マイクボタンは送信ボタン横の既存 `.row` 内に配置(縦方向に UI を肥大化させない)
- 状態遷移: 待機(Mic アイコン) → 録音中(赤・パルス + 経過秒、再押下で停止)
  → 変換中(Spinner、ボタン無効) → 完了(textarea へ追記、待機に戻る)
- 録音中にストリーミング応答が始まっても録音は継続可(挿入先は textarea のみで、
  送信ガードは既存ロジックのまま)
- ボタンは常時表示(extra 未導入でも隠さない。押下時に 503 ヒントを Toast 表示)

## 7. エラー処理

| ケース | 挙動 |
|---|---|
| マイク権限拒否 / デバイスなし | Toast「マイクへのアクセスが拒否されました」 |
| recording extra 未導入(503) | サーバーのヒント文言を Toast 表示(`uv sync --extra recording` 案内) |
| ffmpeg 不在(503)/ 変換失敗(422) | Toast でエラー通知、textarea 変更なし |
| 無音・認識結果空 | Toast「音声を認識できませんでした」、textarea 変更なし |
| サイズ超過(413) | Toast で上限を案内 |
| 録音 120 秒到達 | クライアントが自動停止し通常フローで変換(エラーではない) |

## 8. テスト & 検証ゲート

### テスト
- 統合(`tests/integration/test_api/`):
  - `transcriber_factory` 注入の fake transcriber で正常系(text 連結・duration)
    — 既存 `test_recordings_api.py` パターン
  - extra 未導入時の 503 — 既存 `test_recording_extras_optional.py` パターン
  - 空認識(セグメント 0 件)で `text=""`
  - サイズ超過 413
- 単体: 新規 core ロジックがないため追加なし(ffmpeg コマンド組み立てを関数に切るなら
  その関数のみ単体対象)

### 検証ゲート(必須)
- GUI 変更のため、自動テスト GREEN だけでは PASS にしない。
  evaluator による実機スクリーンショット検証(マイクボタン表示・録音中状態・
  認識テキスト挿入)を PASS 条件に含める

## 9. リスク / 留意点

- **初回レイテンシ**: transcriber が未ロードの場合、初回リクエストで WhisperModel の
  ロード(数秒〜十数秒)が走る。録音ソース機能と共用キャッシュなので 2 回目以降は即時
- **同時実行**: Transcriber は `_serial_lock` で直列化済み。会議録音のライブ字幕と
  チャット音声入力が同時に走ると後着が待たされる(壊れはしない)
- **ブラウザ差**: MediaRecorder の既定 mimeType は Chrome=webm/opus、Safari=mp4/aac。
  ffmpeg デコードなので両対応だが、検証は Chrome を一次対象とする
- **HTTPS 制約**: getUserMedia は secure context 必須。localhost は平文 HTTP でも
  動作するため、本アプリの利用形態(ローカル)では問題なし
