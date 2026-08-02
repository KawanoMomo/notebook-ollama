---
type: spec
title: 録音ソース機能
summary: "マイク+システム音を録音→オフライン文字起こし/話者分離→整形テキストをRAGソース化、引用から元音声を再生。"
aliases:
  - 録音ソース
status: approved
status_inferred: true
date: 2026-06-17
project: NotebookOllama
area: recording
tags:
  - spec
code:
  - apps/web/src/routes/settings
  - core/generation/citations.py
  - core/generation/locations.py
  - core/recording
  - core/retrieval/search.py
  - core/storage/chunks_repo.py
  - core/storage/vector_store.py
---

# 設計仕様: 録音ソース機能(Notebook Ollama)

- 日付: 2026-06-17
- 対象リポジトリ: `10_NotebookOllama`
- 移植元: `04_MeetingTranscriber`(private: KawanoMomo/meeting-transcriber)
- UIモック(合意済み): `docs/mocks/recording-ui-moc.html` / `docs/mocks/settings-ui-moc.html`

## 1. 目的

Notebook Ollama のソース追加に「録音」を加える。マイク + システム音をサーバ側で録音し、
停止後に高精度なオフライン変換(文字起こし → 話者分離 → 名前予想 → LLM補正 → チャンク化 → 埋め込み)を行い、
**整形済みテキストを RAG ソースとして登録**する。録音音声は圧縮保存し、**引用チャンクから元音声の該当箇所を再生**できる。

## 2. スコープ

### やること
- ソース追加エリアからの**録音**(マイク + システム音、サーバ側 WASAPI 録音、`recorder.py` 流用)
- **リアルタイム字幕**(あなた / 相手 の2値)+ **ON/OFF トグル**(重いので即時切替)
- 停止後の**高精度オフライン変換**(PCリソース投入可):
  全文 STT → 話者分離(複数人)→ 名前予想(声紋横断 + **LLM内容推定=新規**)→ **LLM補正**(RAG整形)→ チャンク化(時刻・話者を集約)→ 埋め込み
- 録音音声の**圧縮保存(AAC/.m4a)**と、**引用チャンク → 該当箇所の音声再生**(精密)

### やらないこと(v1 非ゴール)
- リアルタイム翻訳 / 翻訳全般
- 録音中のライブ要約・ライブタスク抽出(MeetingTranscriber にはあるが対象外)
- ブラウザ側(getUserMedia/MediaRecorder)録音 — サーバ側 WASAPI 録音に統一

## 3. 主要な意思決定(確定事項)

| # | 論点 | 決定 |
|---|---|---|
| D1 | 録音対象 | マイク + システム音の両方(サーバ側 WASAPI / `pyaudiowpatch`) |
| D2 | RAGソースの実体 | 文字起こし → **LLM補正済みテキスト**(音声は埋め込まない) |
| D3 | リアルタイム字幕 | 入れる。ただし **ON/OFFトグル**で即切替。**プレビュー専用**(RAGは停止後に別途生成) |
| D4 | 字幕の話者粒度 | あなた / 相手 の2値(チャンネルベース、diarization不要) |
| D5 | RAG変換時の話者粒度 | **話者分離で複数人に分離**(相手1/相手2…)。リソース投入可 |
| D6 | 名前予想 | **声紋横断命名(移植) + LLM内容推定(新規)** の両方 |
| D7 | 引用→音声トレーサビリティ | **チャンク→該当箇所を再生(精密)**。`start_ms/end_ms/speaker` をチャンクまで保持 |
| D8 | 取込方式 | MeetingTranscriber モジュールを **NotebookOllama 内にベンダリング**(`core/recording/`) |
| D9 | 音声保存形式 | 録音中・変換中は WAV → 完了後 **ffmpeg で AAC(.m4a)へ変換、WAVは削除** |
| D10 | UI | モーダルなし。録音中は**センターのチャット領域がライブ字幕ビューに切替**。操作は**サイドバー**に集約。デバイス選択は**設定タブ**に集約 |

## 4. 全体フロー

```
[サイドバー: 録音アイコン] 開始
   ├─ サーバ録音 mic.wav + system.wav (16kHz mono PCM)
   ├─ (トグルON時) ライブ字幕: VAD + faster-whisper → WebSocket → センター領域に表示(あなた/相手)
   └─ 停止
        └─ オフライン高精度パイプライン(サイドバーに詳細ステップ進捗 / SSE)
             → 圧縮変換(AAC) → RAGソース status=ready
```

**ライブ字幕はプレビュー専用**。RAGソースは停止後に必ず高精度パイプラインで生成する
(精度最優先。ライブ/オフラインの整合という複雑性も回避)。

## 5. オフライン高精度パイプライン(順序)

1. `mic.wav` / `system.wav` を faster-whisper で全文 STT(mic は話者「あなた」固定)
2. `system.wav` を sherpa-onnx で**話者分離** → 相手1 / 相手2 … を割当(merge)
3. **声紋横断命名**(`best_named_match` 流用): 過去に命名した声紋と一致すれば自動命名
4. **LLM 名前推定(新規)**: 全文の発話手がかり(例「○○さんお願いします」)で未命名話者の名前を推定
   - 信頼度しきい値(既定 0.65)未満は「相手N」のまま。あくまで提案で、UIで編集可
   - 声紋一致が優先。競合時は声紋を採用
5. **LLM 補正(セグメント単位 = セグメント整合補正)**: 各セグメントの `start_ms/end_ms/speaker` を保持したまま整形
   - 全文一括補正だとタイムスタンプ対応が崩れるため、**セグメント単位(またはセグメント境界を保つ小バッチ)**で補正する
   - `04_MeetingTranscriber` の `correct_segments`(件数を保つ zip マッピング)の方針を流用
6. **チャンク化**: 同一話者の連続セグメントをトークン予算内でまとめ、`start_ms..end_ms` と `speaker` を集約
7. 埋め込み → ベクトルストア upsert、チャンク行 insert
8. **圧縮変換**: ffmpeg で `mic.wav`+`system.wav` を AAC(.m4a)へ変換 → WAV 削除
9. ソース status を `ready` に更新

各ステップ完了時に SSE で進捗を publish(サイドバーの詳細ステップ表示に反映)。

## 6. データモデル改修(タイムスタンプ / 話者をチャンクまで通す)

引用 → 再生のため、既存の各層に **`start_ms` / `end_ms` / `speaker`** を追加する。

| 層 | ファイル | 改修 |
|---|---|---|
| sqlite chunks | `core/storage/chunks_repo.py` | `start_ms` `end_ms` `speaker` カラム追加(nullable。既存ソースは null) |
| ベクトルpayload | `core/storage/vector_store.py` | `ChunkVector` / payload / `SearchHit` に同フィールド追加 |
| 検索結果 | `core/retrieval/search.py` | `RetrievedChunk` に同フィールド追加 |
| ロケーション表示 | `core/generation/locations.py` | 録音ソースは `00:12:34・相手1` 形式で表示する分岐を追加 |
| 引用仕様 | `core/generation/citations.py` / `stream.py` | `CitationSpec` に音声参照(`source_id` + `start_ms` + `channel`)を追加 |
| ソース種別 | — | 新種別 `recording`。取り込みは**パーサ経由ではなく専用パイプライン**(テキスト+時刻+話者が既にあるため) |

- DB マイグレーション: `chunks` への ADD COLUMN(後方互換、既存行 null)。
- `recording` ソースの生セグメント(時刻・話者)は再チャンク/再生のため軽量に永続化する
  (`recording_segments` テーブル、または chunks にスパンを集約保持。最小構成を選ぶ)。

## 7. 音声保存と再生(引用 → 該当箇所)

- 変換中: `data/sources/<source_id>/mic.wav`, `system.wav`
- 完了後: `data/sources/<source_id>/audio.m4a`(チャンネル別に持つ場合は `mic.m4a` / `system.m4a`)
  - 既定はチャンネル別保持(話者→再生対象チャンネルを `あなた=mic / 相手系=system` で決めるため)
- **Range 対応の音声配信エンドポイント**を移植(`04_MeetingTranscriber/app/api/rest.py` の seek 配信)
- 再生: 引用クリック → 話者から対象チャンネル決定 → `audio.currentTime = start_ms/1000` でシーク再生
- 設定で保存形式(AAC/Opus/MP3/WAV)・ビットレート(既定 64kbps)・保持ON/OFF を選択可能

## 8. バックエンド API(NotebookOllama 側 / 新規)

| メソッド | パス | 役割 |
|---|---|---|
| GET | `/api/audio-devices` | 入力デバイス列挙(設定タブ用) |
| POST | `/api/notebooks/{id}/recordings` | 録音開始(`live_caption: bool`、device 上書き可) |
| POST | `/api/notebooks/{id}/recordings/{sid}/stop` | 停止 → オフラインパイプライン投入 |
| PUT | `/api/notebooks/{id}/recordings/{sid}/live-gain` | 録音中の手動ブースト(mic/sys) |
| WS | `/ws/recordings/{sid}/live` | ライブ字幕の push(`ws.py` 方式を移植) |
| GET | `/api/notebooks/{id}/sources/{source_id}/audio?channel=mic\|system` | Range 対応の音声配信 |

- 同時録音は**1本に制限**(409 ガードを移植)。
- ソース取り込み状態は既存 SSE(`events.py`)で配信。ライブ字幕のみ WS。

## 9. ベンダリング構成(`core/recording/`)

`04_MeetingTranscriber` から以下を NotebookOllama に取り込み・適応する:
- `recorder.py`(WASAPI loopback + mic 同時録音)
- `transcriber.py`(faster-whisper ラッパ)
- `live_caption.py`(VAD + 逐次STT)/ `agc.py` / `levels.py`
- `diarizer.py` / `live_diarizer.py`(sherpa-onnx)/ `embeddings.py`(声紋)
- `postprocess.py`(`correct_segments` をセグメント整合補正として利用)
- 新規: **LLM 名前推定モジュール**(`name_inference.py`)
- 新規: **圧縮変換モジュール**(ffmpeg ラッパ、`audio_export.py`)
- 新規: **録音取り込みパイプライン**(`recording_pipeline.py`、§5 の順序を実装)

依存(NotebookOllama `pyproject.toml` に追加): `faster-whisper` `ctranslate2` `pyaudiowpatch`
`sherpa-onnx` `webrtcvad` `pyannote`(必要分)、外部ツール `ffmpeg`。重いので extras 化を検討。
GPU(CUDA)構成・env(モデルサイズ / device / compute_type)は MeetingTranscriber と同等を設定へ追加。

### ベンダリング時の著作権監査(必須)
`04_MeetingTranscriber` は検証用プロジェクトで中身が未精査のため、**第三者の著作ソースコードが
混入している可能性がある**。各モジュールを移植する前に監査する:
- 移植対象ファイルごとに、ライセンスヘッダ / 出所コメント / 明らかなコピー片(他OSSからの貼付)を確認
- 第三者著作のコードが含まれる場合は、**MITリポジトリに実体として組み込まない**。代替実装に置換、
  または依存ライブラリ経由(非同梱)に切り替える。やむを得ず含める場合は当該ライセンスを
  `LICENSE-THIRDPARTY.md` に明記し、ファイル単位で出所を残す
- 監査結果(対象ファイル・判定・対処)を記録し、コミットメッセージ/PRで追跡可能にする

## 10. UI(合意済みモック準拠)

### メイン(`apps/web`)
- サイドバー(`SourcesPanel`)ヘッダーに**録音アイコン**(アイコンのみ、ホバーで「録音」ツールチップ)。「追加」の隣、はみ出さない 30px ボタン
- 録音アイコン直下に**ライブ字幕トグル**のスリムなストリップを常設
- 録音中: サイドバーの録音ストリップに **録音インジケータ + タイマー + 停止 + 字幕トグル + ミニレベルメータ**
- 録音中: **センターのチャット領域がライブ字幕ビュー**に切替(あなた=青 / 相手=緑、確定行 + 暫定行、プレビュー注記)
- 停止後: 録音カード直下に**詳細ステップ(✓式)の変換進捗**(サイドバー完結)。この詳細表示は既存の文書取り込みステータス改善にも適用
- 録音ソースカード: 🎙アイコン / kind=`recording` / 長さ / status
- 右ビューア: 引用チャンク表示に**音声プレーヤー**(話者チップ + シーク + 「この箇所を再生」)。話者名は推定でクリック修正可

### 設定(`apps/web/src/routes/settings`)
- 設定内に**左ナビ**を新設。既存項目(モデル・Ollama / 生成・検索 / ストレージ / モデル一覧)を再配置
- 新規セクション「**音声・録音**」:
  - 入力デバイス(マイク / システム音 / 再スキャン)
  - 文字起こし(Whisperモデル / 実行デバイス・GPUバッジ / compute_type / 言語)
  - ライブ字幕(既定ON / AGC / 手動ブースト上限)
  - 話者分離・名前予想(分離トグル / 最大話者数 / 声紋横断 / **LLM内容推定** / 採用しきい値)
  - 録音データの保存(保存形式=AAC既定 / ビットレート=64kbps既定 / 保持ON/OFF / 保存先注記)

- **GUI 変更は MOC 合意済み**。実装時は SvelteKit コンポーネント(`RecordingModal` ではなく
  `RecordingControls.svelte` / `LiveCaptionView.svelte` / `RecordingConvStatus.svelte` /
  `AudioCitationPlayer.svelte` 等)として既存デザイントークンで作成。

## 11. 進め方 & テスト & 検証ゲート

### スプリント単位の進行(必須)
- 機能を**スプリントに分割**し、**各スプリント完了時に Playwright MCP で実機検証**してから次へ進む
- 検証は evaluator(Playwright MCP 前提)で実施し、証拠(スクショ + 観測ログ)付き report を残す
- スプリント例(プラン段階で確定):
  1. データモデル改修(chunks に時刻/話者、ベクトルpayload、search/locations)— API/単体
  2. ベンダリング + 録音開始/停止 + 音声配信(Range)— 実機録音の最小確認
  3. ライブ字幕(WS + トグル + センター切替UI)— Playwright で表示確認
  4. オフラインパイプライン(STT→話者分離→名前予想→補正→チャンク→埋め込み)
  5. 引用→音声再生 UI + 変換ステップ表示(サイドバー)
  6. 設定タブ(音声・録音)+ AAC圧縮変換
- 各スプリントは TDD(red-green-refactor)を基本とする

### テスト
- ユニット: チャンク時刻集約 / セグメント整合補正の対応保持 / LLM名前推定パーサ / ffmpeg変換コマンド生成
- 統合: fake ollama、heavy STT/diarization はマーカー分離(`-m audio` 等で既定スキップ)
- **視覚検証(必須)**: 録音UI・ライブ字幕・変換ステップ・引用再生は **Playwright MCP / Evaluator スクショ必須**。
  自動テスト GREEN だけで PASS にしない(visual regression を検出するため)

## 12. ライセンス & リポジトリ構成

本プロジェクトは **MIT**。第三者(他者)の著作物のみ分離管理する(自分自身のMITコードは `core/` に混在可)。

- **第三者の依存ライブラリ**: `pyproject.toml` 経由で取得し**同梱しない**。`uv.lock` で固定
- **第三者のモデル**(Whisper / 話者分離 / 埋め込み): setup スクリプトで DL し **gitignore**(リポジトリに含めない)
- **録音音声 / DB / ベクトル**: `data/`(gitignore 済)に保存しリポジトリに含めない
- **ライセンス追跡**: 新規依存・モデルを `LICENSE-THIRDPARTY.md` に追記。本体は `LICENSE`(MIT)
- **ベンダリングコードの監査**: §9 の通り、MeetingTranscriber 由来コードに第三者著作が混入していないか
  移植時に確認し、混入分は実体組込みを避ける(置換 or 依存化)
- 結果として「**今回作成 + 自分のMITコード(コミット対象)**」と「**第三者の依存・モデル(非同梱)**」が
  構成上分離され、push 時に他者著作物を実体として含めない

## 13. リスク / 留意点

- **セグメント整合補正の限界**: 全文一括補正に比べ、文跨ぎの整形は弱くなる(タイムスタンプ整合とのトレードオフ)。
- **LLM 名前推定の誤り**: 推定名は誤る可能性があるため、しきい値 + UI 修正前提。既定で控えめに採用。
- **AAC からの再処理**: 再起こしは非可逆圧縮後の音声を使うため STT 精度が WAV よりわずかに落ちうる。
- **依存の重さ**: NotebookOllama のインストールフットプリントが大きくなる(extras 化で緩和)。
- **デバイス競合**: 単一サーバ・単一録音前提(409 ガード)。
