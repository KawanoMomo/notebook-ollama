# 設計仕様: YouTube ソース機能(Notebook Ollama) — 【保留 / DEFERRED】

- 日付: 2026-06-21
- 対象リポジトリ: `10_NotebookOllama`
- ステータス: **保留(DEFERRED)** — 設計メモのみ。実装は未着手。実装着手にはメンテナのガバナンス判断(後述 §7)が必要。
- 機能元: Google NotebookLM の「YouTube 動画をソースに追加」機能
- 調査根拠: deep-research レポート(2026-06-21、105 エージェント / 23 ソース / 25 主張を 3 票制で検証、23 確認・2 棄却)

## 0. なぜ保留なのか(最初に結論)

機能としては魅力的で、しかも **NotebookLM を超える価値(タイムスタンプ・ディープリンク引用)** を出せる。
しかし以下の 2 点により、**コア機能には組み込まず、設計だけ確定して保留**とする。

1. **依存ライブラリ(`yt-dlp`)が「移動標的」**。YouTube の anti-bot(PO-token / SABR 等)で過去に `pytube` / `youtube-transcript-api` が複数回壊れており、`yt-dlp` も例外でなく、リリース間で突然壊れうる。コア機能に組み込むとメンテ負担が読めない。
2. **YouTube ToS 抵触のグレーゾーン**。自分(プロジェクト)のライセンスでは許される依存だが、エンドユーザーが実行する時点で第三者サービス(YouTube)の ToS に抵触しうる。同梱の是非は技術判断でなく**メンテナのガバナンス判断**。

→ 採用するなら **opt-in extra**(PDF/PyMuPDF と同じパターン)に限定する。

## 1. 目的

Notebook Ollama のソース追加に「YouTube 動画」を加える。
動画の**字幕(transcript)テキストを RAG ソースとして登録**し、引用時には**動画の該当タイムスタンプへディープリンク**できるようにする。

## 2. 調査で判明した NotebookLM の実態(一次ソース確認済み)

| 項目 | 事実 | 出典 |
|---|---|---|
| 取り込み方式 | **字幕テキストのみ**。動画・音声・フレームは取り込まない | Google公式 `support.google.com/notebooklm/answer/16215270` |
| ASR | NotebookLM は**自前で文字起こししない**。YouTube 既存字幕(手動 or 自動生成)に依存 | 公式 + コミュニティ 3-0 |
| 字幕なし動画 | **非対応**(「字幕ファイルがない」「発話がない」はインポート失敗) | 公式 |
| 対応 URL | **公開動画のみ**(非公開・限定公開・年齢制限は不可) | 公式 |
| 長さ制限 | 動画尺の上限なし。ただし**字幕 50 万語**を超えると不可 | 公式 |
| 引用形式 | **字幕テキストへのインライン引用**。タイムスタンプにディープリンクしない(意図的設計) | 公式blog + コミュニティ 3-0 |

> 要約: NotebookLM の YouTube 対応は「**YouTube の既存字幕を引っぱってテキストソースにするだけ**」。
> Google だから内部 ASR を使っているという推測は **否定された**。Notebook Ollama も同じ「字幕取得 → テキスト化」で機能パリティを満たせる。

## 3. 技術選定(オープンソース現況 2025-2026)

| ライブラリ | 状況 | ライセンス | 採否 |
|---|---|---|---|
| `pytube` | YouTube anti-bot で**破損** | Unlicense | ✗ |
| `youtube-transcript-api` | 1.2.2 で API 破壊変更、`RequestBlocked` 多発、破損履歴あり | MIT | ✗(単独では不安定) |
| **`yt-dlp`** | **現在最も信頼できる**。LangChain が公式に乗り換え済み(旧ローダーは 404) | **Unlicense(パブリックドメイン)** | **採用** |
| YouTube Data API v3 (captions) | OAuth(`youtube.force-ssl`)必須・1 list = 50 quota units・**`captions.download` は認証ユーザー所有の字幕にしか成功しない** → 任意公開動画には**根本的に使えない** | — | ✗ |
| ローカル Whisper(字幕なし動画用) | yt-dlp が字幕なしと報告したときのみ起動する**フォールバック** | — | △(opt-in の中の opt-in) |

- **ライセンス確認**: `yt-dlp` の LICENSE は Unlicense(逐語: "This is free and unencumbered software released into the public domain.")。PyPI sdist/wheel 経由は Unlicense で **AGPL 回避方針と互換**。
  - 注意: PyInstaller バンドルの standalone `.exe`/`_macos` バイナリのみ GPLv3+。Notebook Ollama は **PyPI 経由で取り込む**ため該当しない。
  - 注意: Unlicense は OSI が「drafting が雑」と評価。帰属表記は保守的に運用すること(README に yt-dlp 利用を明記)。

## 4. 主要な意思決定(案 — 実装着手時に再確認)

| # | 論点 | 決定(案) |
|---|---|---|
| D1 | 取り込み実体 | **字幕テキストのみ**(NotebookLM と同じ)。動画・音声は埋め込まない |
| D2 | 字幕取得ライブラリ | **`yt-dlp`**(`--write-auto-subs` / `--write-subs`、メタデータ取得込み) |
| D3 | 配布形態 | **opt-in extra** `notebook-ollama[youtube]`(PDF/PyMuPDF と同じパターン) |
| D4 | source kind | `web` とは**別の新 kind `youtube`** |
| D5 | 字幕なし動画 | **ローカル Whisper フォールバック**(opt-in の中の opt-in。yt-dlp が字幕なし報告時のみ。要 ASR 可能環境) |
| D6 | タイムスタンプ保持 | **`heading_path` に入れない**。`ParsedSection` に**新フィールド** `start_seconds` / `end_seconds` を追加して保持 |
| D7 | チャプター | yt-dlp がチャプター情報を返せば **`heading_path` にチャプター名**、なければ `NN:NN` 時間窓ラベル |
| D8 | セクション分割 | 字幕セグメントを **400-800 トークン**にグループ化(無音境界 or 1 分窓)。既存 chunker に合わせる |
| D9 | 引用 UX | **NotebookLM を超える** — `https://youtu.be/<id>?t=<秒>` でタイムスタンプ・ディープリンク |
| D10 | エラー処理 | 「字幕取得失敗」を**例外でなくユーザー向けエラー状態**として一級扱い(YouTube 側変更で壊れる前提) |

## 5. アーキテクチャ移植マッピング

既存の Parser registry パターンにそのまま乗る。

```
core/ingestion/parsers/youtube.py   (新規, opt-in extra)
  class YouTubeParser(Parser):
    kind = "youtube"
    parse(url) -> ParsedDocument:
      1. yt-dlp で字幕 + メタデータ(title/channel/duration/chapters)取得
      2. 字幕なし → Whisper フォールバック(opt-in) or エラー状態
      3. 字幕セグメントを 400-800 トークンにグループ化
      4. 各 ParsedSection に start_seconds/end_seconds を付与
      5. チャプターあり → heading_path にチャプター名
         チャプターなし → "00:12:30" 形式の時間窓ラベル
```

- `ParsedSection` への**新フィールド追加**(`start_seconds` / `end_seconds`)が唯一の既存コードへの変更点。他 parser は `None` のままで後方互換。
- ステータスパイプライン(pending→parsing→chunking→embedding→ready)は**そのまま適合**。長尺動画の `parsing` は数分かかるので進捗を SSE で emit。
- MCP の `get_source_outline` でタイムスタンプを露出可能。

## 6. UI 考慮(案)

- ソース追加モーダルに「YouTube URL」タブ(既存の Web URL タブと並列)。
- ソースカード: サムネイル + タイトル + チャンネル + 尺。yt-dlp メタデータから取得。
- 引用クリック時: **タイムスタンプ付き YouTube リンク**を新規タブで開く(NotebookLM はテキストのみ → ここで差別化)。
- extra 未インストール時: YouTube タブを無効化し「`notebook-ollama[youtube]` で有効化」と表示(PDF と同じ UX)。

## 7. 保留解除の判断材料(実装着手前に解決すべきこと)

実装を「GO」に進めるには、以下を解決すること。

1. **【ガバナンス・メンテナ判断】** 自分のライセンスでは許されるが、エンドユーザー実行時に第三者(YouTube)の ToS に抵触しうる依存(yt-dlp)を opt-in で同梱する是非。これは技術でなく方針判断。
2. **【技術・実装時検証】** yt-dlp の `--write-auto-subs` が当該時点で認証なしに動くか(PO-token / SABR で Cookie 認証が必須化していないか)。yt-dlp issue tracker を確認。
3. **【品質】** 自動字幕は句読点・話者区切りがない。sentence-aware chunker が機能するか、文復元 LLM パスが必要か要検証。

## 8. ToS / 法的メモ(※法的助言ではなく情報提供)

- YouTube Developer Policies III.E.1.a: "download, import, backup, cache, or store copies of YouTube audiovisual content without YouTube's prior written approval" を**禁止**。
- III.E.6: スクレイピング・未文書化 API 使用を禁止。
- 公式ルート(Data API v3 captions)は OAuth 必須・50 units/list・**所有字幕しか download できない** → 任意公開動画の取り込みには使えない。
- リスク所在: ライブラリを**配布**することと、ユーザーが**ローカル実行**することでリスク負担が異なる。yt-dlp 本体への公開 DMCA テイクダウンは 2026 年半ば時点で未確認(ただし youtube-dl には過去に争われた事例あり)。
- **同等のリスクを LangChain / LlamaIndex / yt-dlp 自体が既に負っている**。Notebook Ollama 固有の新規リスクではない。

## 9. 判定サマリ

**GO-WITH-CAVEATS(条件付き実装可)/ ただし現時点は DEFERRED(保留)**

- やるなら opt-in extra(`notebook-ollama[youtube]`)で yt-dlp ベース。
- タイムスタンプ・ディープリンクで NotebookLM を超えられる点が技術的魅力。
- 保留理由は「移動標的の依存」+「ToS グレーゾーン同梱のガバナンス判断未了」。
- §7 の 3 点が解決したら、この設計メモをもとにブレインストーミング → 実装プランへ進める。
