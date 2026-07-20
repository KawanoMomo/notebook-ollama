---
type: spec
title: 録音チャンネル個別ミュート + 話者名一括リネーム
summary: "録音チャンネルの個別ミュートと話者名の一括リネーム。"
aliases:
  - 録音ミュート
  - 話者リネーム
status: review
date: 2026-06-22
project: NotebookOllama
area: recording
tags:
  - spec
related:
  - "[[2026-06-17-recording-source-design]]"
  - "[[2026-06-19-recording-naming-design]]"
---

# 設計仕様: 録音チャンネル個別ミュート + 話者名一括リネーム(Notebook Ollama)

- 日付: 2026-06-22
- 対象リポジトリ: `10_NotebookOllama`
- ブランチ: `feature/model-selection`
- ステータス: **設計合意待ち** — ユーザーレビュー後に実装着手。GUI 変更を含むため MOC 合意 + 実機スクショ検証(Evaluator)が必須。
- 関連設計: `2026-06-17-recording-source-design.md`(録音本体), `2026-06-19-recording-naming-design.md`(命名)
- 由来: 実機レビュー時のユーザーフィードバック 3 点(①は実装済みのため本仕様は②③)

## 0. 背景: フィードバック 3 点の調査結果

| # | フィードバック | 現状 | 本仕様の対象 |
|---|---|---|---|
| ① | オーディオソース名に LLM 補正がかかっているか確認 | **実装済み**(`title_inference.py` + pipeline step4.5)。best-effort なので失敗時はフォールバック | 対象外(別途ログ確認) |
| ② | 録音中に各チャンネル(マイク/システム音)を Teams 風にミュートし、ライブ字幕・変換・推論から除外 | **未実装** | **本仕様 §2** |
| ③ | 会話履歴で話者名を変更・保持できる UI | **未実装**(表示のみ。設計 CR.5 には記載あり) | **本仕様 §3** |

## 1. 確定した意思決定

| # | 論点 | 決定 |
|---|---|---|
| M1 | ②ミュートの粒度 | **時間区間ミュート(Teams 風)**。押した瞬間〜解除までの区間だけ除外 |
| M2 | ②除外の範囲 | ライブ字幕 + **停止後オフライン変換** + 推論/埋め込み すべてから除外 |
| M3 | ③リネームの反映範囲 | **話者単位で一括**。「相手1」→「田中さん」でその録音内の全「相手1」発言を更新 |
| M4 | ③リネームのスコープ | **その録音(source)内のみ**。録音横断の声紋命名は既存 D6 の領分で本仕様の対象外 |

## 2. 機能②: 録音中チャンネル個別ミュート

### 2.1 やること / やらないこと

**やること**
- 録音中、マイク(`あなた`)とシステム音(`相手`)を**個別に**ミュート/アンミュート
- ミュート中の区間は: ライブ字幕に出さない / 停止後オフライン変換で文字起こし結果を破棄 / チャンク化・埋め込み・LLM 推論に渡さない
- ミュート操作は録音中いつでも何度でも可(Teams のマイクボタン同様)

**やらないこと(v1 非ゴール)**
- 録音した生 WAV からのミュート区間の物理削除(WAV は完全な原本として残す。除外は下流処理で行う)
- 区間の後編集(録音停止後にミュート区間を追加/削除する UI)

### 2.2 UI(MOC 合意対象)

`apps/web/src/lib/components/RecordingControls.svelte`(行60-65 の既存レベルメータ隣)に**チャンネルトグルボタン**を追加。

```
┌─ 録音中 00:03:12 ────────────────────────────┐
│  ● REC   [ライブ字幕 ON/OFF]                  │
│                                               │
│  🎤 あなた    ▓▓▓▓░░░  [🎤 ボタン]  ← クリックでミュート
│  🔊 相手      ▓▓░░░░░  [🔊 ボタン]  ← クリックでミュート
└───────────────────────────────────────────────┘
```

- ミュート状態の視覚表現: アイコンに**スラッシュ(🎤→🔇)** + ボタンを赤系/dim、該当行のレベルメータをグレーアウト
- ライブ字幕ビュー(`LiveCaptionView.svelte`)では、ミュート中チャンネルの新規字幕は**追加しない**(過去分は残す)
- 既存の「ライブ字幕 ON/OFF」トグルは全体スイッチとして残す(チャンネルミュートと独立)

### 2.3 データモデル

ミュート区間をチャンネルごとに記録する。録音セッション中はメモリ上、停止時にサイドカー JSON へ永続化。

```
録音ディレクトリ/
  mic.wav
  system.wav
  mute_intervals.json   ← 新規
```

`mute_intervals.json`:
```json
{
  "mic":    [{"start_ms": 70000, "end_ms": 95000}],
  "system": []
}
```

- 時間基準: 録音開始 = 0ms。ミュート ON で区間開始、OFF で区間確定。
- 録音停止時にミュート中だったチャンネルは `end_ms = 録音終了時刻` でクローズ。

### 2.4 WS プロトコル拡張(双方向化)

現状 `recording_ws.py` の WS はサーバ→クライアントの単方向。**クライアント→サーバのミュートコマンド**を追加する。

クライアント→サーバ(新規):
```json
{ "type": "mute",   "channel": "mic" | "system", "muted": true | false }
```
- サーバはコマンド受信時刻(録音開始からの相対 ms)で区間を開閉
- `muted:true` → その区間の開始を記録 + 以降そのチャンネルのフレームをライブ STT へ送らない + `caption`/`level` の送出を止める(レベルはグレーアウト用に 0 を送るか停止)
- `muted:false` → 区間を確定 + ライブ STT への供給を再開

サーバ→クライアント(既存 `caption`/`level`/`info` に加え、状態同期用に任意):
```json
{ "type": "mute_state", "channel": "mic", "muted": true }
```

### 2.5 オフライン変換での除外

`core/recording/recording_pipeline.py` を拡張:

1. パイプライン開始時に `mute_intervals.json` を読み込む
2. 各チャンネルの STT 結果セグメント(`start_ms`/`end_ms` を持つ)について、**該当チャンネルのミュート区間と重なるセグメントを破棄**する
   - 重なり判定: セグメント区間とミュート区間が一部でも重なれば除外(保守的)
3. 除外は **整文(`correct_segments_aligned`)・話者分離・チャンク化・埋め込みより前**に行う → ミュート区間は LLM 推論にも埋め込みにも一切到達しない(M2 充足)

**実装上の割り切り**: STT 自体はミュート区間にも走る(WAV は完全原本)。ただし出力セグメントを下流に渡す前に破棄するため、ユーザーから見える結果・LLM 入力・埋め込みには反映されない。真の「STT スキップ」(ミュート区間を STT に渡さない)は CPU 節約の最適化として将来課題。

### 2.6 触るファイル

```
フロント
├─ apps/web/src/lib/stores/recording.svelte.ts
│   └─ micMuted/systemMuted state、toggleMute(channel) を追加(WS send)
├─ apps/web/src/lib/components/RecordingControls.svelte
│   └─ チャンネルミュートボタン + 視覚状態(行60-65 隣)
└─ apps/web/src/lib/components/LiveCaptionView.svelte
    └─ ミュート中チャンネルの新規字幕を抑止(任意: ストア側で抑止済みなら不要)
バックエンド
├─ apps/api/routers/recording_ws.py
│   └─ クライアント→サーバ "mute" コマンド受信、区間記録、ライブ STT 供給制御
├─ core/recording/recorder.py(または live_caption.py)
│   └─ チャンネル別フレームをライブ STT に流す/止めるフック
└─ core/recording/recording_pipeline.py
    └─ mute_intervals.json 読み込み + セグメント除外(STT後・整文前)
```

## 3. 機能③: 会話履歴の話者名一括リネーム

### 3.1 やること / やらないこと

**やること**
- 右パネル(会話履歴 / 引用チャンク表示)で話者チップをクリック → インライン編集 → その録音内の**同一話者ラベルの全チャンクを一括リネーム**
- 変更を DB(SQLite `chunks.speaker`)+ ベクトルストア(Qdrant payload)に永続化

**やらないこと(v1 非ゴール)**
- 録音横断の話者名同期(声紋ベース命名は既存 D6 の領分)
- 1 チャンクだけ別名にする個別上書き(M3 で一括に確定)

### 3.2 UI(MOC 合意対象)

`apps/web/src/lib/components/AudioCitationPlayer.svelte`(行146 の話者チップ)を**クリック編集可**にする。`SourceCard.svelte`(行66-97)の既存インライン編集パターンを流用。

```
通常:   [● 相手1]  00:12:30–00:12:48   [この箇所を再生 ▶]
              ↑ クリック
編集中: [● (入力欄: 田中さん___) ✓ ✕]
```

- チップクリック → テキスト入力に切替。Enter/✓ で確定、Esc/✕ でキャンセル
- 確定時: 「『相手1』を『田中さん』に変更しますか？(この録音の全 N 件)」を簡易確認 or トースト「N 件の発言を更新しました」
- 編集後、右パネル・チャット内の引用とも表示が新名称に更新

### 3.3 API

新規エンドポイント(source スコープ):
```
PATCH /api/notebooks/{notebook_id}/sources/{source_id}/speaker
body: { "from_label": "相手1", "to_label": "田中さん" }
→ 200 { "updated": 12 }   # 更新チャンク数
```
- `to_label` は空文字不可(検証)
- `from_label` が存在しなければ `updated: 0`

### 3.4 永続化(SQLite + Qdrant 両更新)

`chunks.speaker` は SQLite と Qdrant payload の**両方**に存在する(調査: `vector_store.py` payload に speaker)。両方更新して整合を保つ。

- SQLite: `core/storage/chunks_repo.py` に `rename_speaker_in_source(conn, source_id, from_label, to_label) -> int`
  - `UPDATE chunks SET speaker=? WHERE source_id=? AND speaker=?`
- Qdrant: `core/storage/vector_store.py` に `rename_speaker(source_id, from_label, to_label)`
  - `set_payload` をフィルタ(`source_id` + `speaker==from_label`)付きで適用
- どちらか失敗時は SQLite を正とし、Qdrant は再同期可能(payload の speaker は引用表示用。検索フィルタには使っていないため不整合の影響は表示のみ)

### 3.5 触るファイル

```
フロント
├─ apps/web/src/lib/components/AudioCitationPlayer.svelte
│   └─ 話者チップをインライン編集化(SourceCard パターン流用)
├─ apps/web/src/lib/components/SourceViewer.svelte
│   └─ 編集確定 → API 呼び出し → 表示更新(行138-148 付近)
└─ apps/web/src/lib/api/source_outline.ts(または sources.ts)
    └─ renameSpeaker(notebookId, sourceId, fromLabel, toLabel) 関数
バックエンド
├─ apps/api/routers/sources.py
│   └─ PATCH .../speaker エンドポイント
├─ apps/api/schemas/source_content.py
│   └─ SpeakerRename スキーマ {from_label, to_label}
├─ core/storage/chunks_repo.py
│   └─ rename_speaker_in_source(...) -> int
└─ core/storage/vector_store.py
    └─ rename_speaker(source_id, from_label, to_label)
```

## 4. テスト戦略

- **ユニット/統合(pytest)**
  - ②: ミュート区間とセグメントの重なり判定、`mute_intervals.json` のシリアライズ/読込、パイプラインで除外されたセグメントが chunks に入らないこと
  - ②: WS の "mute" コマンドで区間が開閉されること
  - ③: `rename_speaker_in_source` が該当チャンクのみ更新し件数を返すこと、空 `to_label` で 400、Qdrant payload も更新されること
- **フロント(vitest)**
  - ②: store の `toggleMute` が WS send を呼ぶ、ミュート state で字幕抑止
  - ③: インライン編集の確定/キャンセル、API 呼び出し
- **実機ビジュアル検証(Evaluator/Playwright MCP、CLAUDE.md 必須ゲート)**
  - ②: 録音中にマイクボタンを押す → アイコンがスラッシュ化・行グレーアウト → 該当チャンネルの新規字幕が止まる(スクショ)
  - ③: 話者チップクリック → 入力 → 確定 → 同一話者の全表示が新名称に変わる(スクショ)
  - 自動テスト GREEN だけでは PASS にしない(視覚回帰)

## 5. 実装順序(案)

1. ③ バックエンド(API + repo + vector_store)→ ユニットテスト
2. ③ フロント(インライン編集 + API)→ vitest → 実機スクショ
3. ② データモデル + WS 双方向化(バックエンド)→ テスト
4. ② パイプライン除外 → テスト
5. ② フロント(ミュートボタン + store)→ vitest → 実機スクショ
6. 統合スモーク(実録音 → ミュート → 停止 → 変換 → リネーム)

③ を先にするのは、UI 変更が局所的で WS 拡張を伴わず低リスクなため。② は WS 双方向化とパイプライン変更を伴い影響範囲が広い。

## 6. リスク / 留意点

- ② の WS 双方向化は既存のライブ字幕単方向設計を変える。後方互換のため、古いクライアントが "mute" を送らなくても従来どおり動くこと。
- ② のミュート区間タイムスタンプはクライアント操作時刻ベース。WS 往復遅延で数十〜数百 ms ずれうる。境界は保守的(重なれば除外)にして取りこぼしを防ぐ。
- ③ の Qdrant payload 更新は `set_payload` のフィルタ更新が qdrant-client のバージョンで挙動差がありうる。失敗時は SQLite 正で表示は再 JOIN フォールバック可能にする。
- いずれも GUI 変更 → 実機スクショ検証なしに PASS 判定しない(CLAUDE.md / メモリの視覚検証ゲート)。

## 7. 改訂(2026-06-23): ②ミュートを「録音側で無音書き込み」方式に変更

§2.4/§2.5 の **時間区間ミュート(壁時計区間 + オフラインのタイムスタンプ除外)** は、実音声 E2E で破綻が判明したため廃止し、**録音側で無音書き込み** 方式に変更した。

### 7.1 なぜ変えたか(実証)
- `recorder.py` は WASAPI ループバックのアイドル時フレームを書かない(`get_read_available() < 1024` で `continue`)。実測 **mic.m4a=94.5s / system.m4a=32.8s**(同一録音)。
- → system WAV は「音があった区間だけ」を詰めた **圧縮タイムライン**。壁時計のミュート区間を **定数オフセットでは WAV 位置へ写像できない(非線形)**。
- 実際、初回 E2E ではミュート中発話が漏洩し、非ミュート発話が誤除外された。per-channel offset 化(当初の修正)でも loopback は救えない。

### 7.2 確定した方式(M1 改)
- **録音側ミュート**: ミュート中チャンネルの WAV に実音声でなく **無音(zeros)** を書く(`recorder.py` の `mute_check`)。
- ライブ字幕は従来どおり on_chunk ゲートで抑止。
- オフラインは無音 → VAD 除去で自動的に何も生成しない。よって変換・話者分離・整文・チャンク化・埋め込み・LLM 推論のいずれにもミュート区間が到達しない(M2 充足、タイムスタンプ計算なし)。
- **撤去**: `mute_intervals.json` / オフライン除外フィルタ(`mute_filter.py`)/ `wav_t0`・`wav_start_offset_ms`。`MuteState` はチャンネル別の真偽値ホルダに簡素化。
- 代償(合意済み): WAV は完全原本でなくミュート区間が無音化(事後アンミュート不可)。これは元フィードバック「ミュート中は変換後の音声データに反映しない」に合致。

### 7.3 検証
- 実音声 E2E(ミュート中「秘密のパイナップル」発話)で **漏洩なし・非ミュート保持** を確認: `docs/eval/2026-06-23-mute-integration/`。
