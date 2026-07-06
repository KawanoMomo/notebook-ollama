# [DRAFT] チャット音声入力: ステートレス STT + ブラウザ側 VAD 構成

- 状態: ドラフト(未採番。正式登録はユーザー承認後に /adr で実施)
- 日付: 2026-07-07
- 関連: `docs/specs/2026-07-05-chat-voice-input-design.md`(§3 意思決定表)
- ブランチ: feature/chat-voice-input

## 文脈

チャット音声入力(PTT + ハンズフリー)の実装で、既存の録音ソース機能
(サーバー側キャプチャ + LiveCaption + WebSocket)とは異なる構成を採った。

## 決定

1. **STT エンドポイントはステートレス 1 本**(`POST /api/stt/transcribe`)。
   セッション管理・音声保存を持たず、共有 transcriber(`app.state.transcriber`)を
   `recordings._get_transcriber` 経由で再利用する
2. **ハンズフリーの発話区切りはブラウザ側 RMS VAD**(`apps/web/src/lib/audio/vad.ts`)。
   サーバー側 webrtcvad / LiveCaption / WS ストリーミングは v1 では使わない
   (精度不足時の v2 候補として温存)
3. **STT ハンドラは同期 `def`**(FastAPI threadpool オフロード)。
   `async def` 内での ffmpeg subprocess + Whisper 推論は単一ワーカーの
   イベントループを止め、SSE/ライブ字幕 WS を巻き込むため
4. **音声キャプチャは長押し確定(250ms)時に開始**。keydown 先行開始は
   タップのたびに getUserMedia が走りマイクインジケーターが点滅するため不採用

## 帰結

- サーバーはチャット音声について状態を持たず、会議録音と独立に動作する
  (マイクデバイス競合なし)。Transcriber の `_serial_lock` により同時実行は直列化
- ブラウザ VAD は騒音環境で区切り精度が劣る可能性(定数調整可能。v2 でサーバー側移行の余地)
- 語頭 ~数百 ms のロスは Claude Code の hold ウォームアップ相当として許容
