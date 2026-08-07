---
type: spec
title: 出典表示の刷新 — 根拠スパンのハイライト・原本ページ・選択範囲翻訳
summary: "出典クリック時にチャンク全文が黄色く塗られるだけで根拠箇所が分からない問題を、生成後の字句照合による根拠スパン解決(枝番バッジ+マーカー下線)、PDF原本ページのオンデマンド描画+矩形オーバーレイ、選択範囲のローカルLLM翻訳で解決する。検索・生成経路には一切手を入れない。"
aliases:
  - 出典表示刷新
  - citation-evidence-ui
  - 根拠ハイライト
status: draft
date: 2026-08-07
project: NotebookOllama
area: ui
tags:
  - spec
  - ui
  - rag
  - citation
related:
  - "[[2026-06-19-rag-ux-improvements-design]]"
  - "[[2026-06-25-source-guide-design]]"
  - "[[2026-07-20-beta-feature-flags-design]]"
  - "[[2026-07-20-pdf-table-figure-sidecar-design]]"
code:
  - apps/api/routers/sources.py
  - apps/api/schemas/chat.py
  - apps/api/schemas/settings.py
  - apps/web/src/app.css
  - apps/web/src/lib/components/CitationBadge.svelte
  - apps/web/src/lib/components/SourceViewer.svelte
  - apps/web/src/lib/utils/citations.ts
  - apps/web/src/routes/settings
  - apps/web/tests/unit
  - core/generation/citations.py
  - core/generation/stream.py
  - core/mcp/tools/ask.py
  - core/ollama
  - tests/integration
  - tests/unit
---

# 出典表示の刷新 — 根拠スパンのハイライト・原本ページ・選択範囲翻訳

## 1. 背景と問題

現状の出典表示には4つの問題がある。

1. **根拠箇所が分からない(致命的)** — チャット中の `[^3]` を押すと `SourceViewer` が
   `<pre>{chunk.text}</pre>` でチャンク全文を表示し、`--color-citation-bg` (#fff8c4) で
   全体を一様に塗る。そのチャンクの**どこが**その主張の根拠なのかを示す機構が存在しない。
2. **配色が古く、アプリの意匠から浮いている** — 黄色 (#fff8c4 / #d4a017) はアクセント色
   (#3563e9) と無関係で、アプリ全体のトーンから乖離している。
3. **引用番号が粗い** — 番号はチャンク単位。回答中の複数の主張が同じチャンクを引いていても
   区別がつかない。
4. **英語ソースが読みにくい** — 原文が英語のとき、その場で内容を掴む手段が無い。

加えて、業界の定番(NotebookLM / Perplexity / Acrobat AI Assistant)では「番号クリック →
原本の該当文へスクロール＋その場でハイライト」「答えと原本を並べて見比べる」が共通解に
なっており、本アプリはこの「どの文か」の一段が欠落している。

> [!important] 最優先の制約
> **RAG の検索・生成性能を落とさないこと。** 索引サイズ・ingest 時間・生成トークン数・
> 生成レイテンシを増やす施策は、既定では採らない。増える施策はすべてベータのオプトイン
> ([[005-beta-feature-flag-registry]]) に隔離する。

## 2. スコープ

| # | 対象 | 既定 |
|---|---|---|
| ① | 根拠スパンのハイライト | ON |
| ② | 配色・バッジのデザイン刷新 | ON |
| ③ | 引用番号の枝番化 (`3-1` `3-2`) | ON |
| ④ | PDF 原本ページ画像＋矩形オーバーレイ | ON (PDFソースのみ) |
| ⑤ | 選択範囲のローカルLLM翻訳 | ON (使ったときだけ実行) |
| ⑥ | β: LLM に根拠原文を出力させる引用抽出 | OFF (オプトイン) |

**非スコープ**: チャンク分割方法の変更、検索アルゴリズムの変更、事前のページ画像生成、
録音・テキストソースへの原本表示。

## 3. アーキテクチャ

```
[生成完了] ──> core/generation/evidence_spans.py  (純ロジック / IO なし / LLM 呼び出しなし)
                    │  入力: 回答テキスト, citations, 各 chunk の本文
                    │  出力: Citation.spans = [{ordinal, start, end, quote}]
                    v
             apps/api/schemas/chat.py  (Citation に spans を追加)
                    v
       apps/web/src/lib/utils/citations.ts  (枝番バッジ生成)
       apps/web/src/lib/components/CitationBadge.svelte  (角丸タグ)
       apps/web/src/lib/components/SourceViewer.svelte  (<mark> 描画 / タブ / 翻訳)
                    │
                    ├── GET  /api/sources/{id}/pages/{page}      (原本PNG, オンデマンド+キャッシュ)
                    ├── GET  /api/sources/{id}/pages/{page}/rects (矩形, PyMuPDF search_for)
                    └── POST /api/translate                       (SSE ストリーム)
```

### 3.1 根拠スパン解決 — `core/generation/evidence_spans.py`

生成が完了した**後**に走る後処理。追加の LLM 呼び出し・埋め込み計算はゼロで、CPU 上で
数ミリ秒で完結する。したがって生成レイテンシと検索精度への影響は無い。

アルゴリズム:

1. 回答テキストを走査し、各 `[^n]` の**出現ごと**に、直前の1文(句点・改行・箇条書き記号で
   区切る)を「主張文」として切り出す。
2. 主張文と対象チャンク本文の双方を正規化する(NFKC → 小文字化 → 空白・約物の除去)。
   このとき**正規化後インデックス → 元インデックス**の逆写像表を保持する。
3. 正規化済み主張文とチャンク本文の間で、長さ `n = 6` の文字 n-gram が一致するブロックを
   すべて求め、ブロック群を最も密に覆う連続区間を根拠スパン候補とする。
4. 候補を逆写像でチャンク本文の元 `(start, end)` に戻す。
5. **採否判定**: 主張文の被覆率 ≧ 0.35 かつ 最長連続一致 ≧ 12 文字を満たすときのみ採用。
   満たさなければ `unresolved` とし、そのチャンクにスパンを一切付けない。
6. 採用したスパンに、そのチャンクの引用番号内で 1 起算の `ordinal` を振る(`3-1`, `3-2`)。

呼び出し元は `core/generation/stream.py`(生成完了時の citations 確定箇所)。
`core/mcp/tools/ask.py` からも同じ関数を使う。

> [!note] 未特定を明示する理由
> LLM が言い換えた場合など、字句照合が当たらないケースは必ず存在する。近い箇所を「推定」と
> して光らせると、**誤った箇所を根拠だと信じさせる**。[[016-pixel-native-explicit-failure]]
> と同じ判断で、当たらないときは黙る。

### 3.2 スキーマ

`apps/api/schemas/chat.py` / `core/generation/citations.py` の `Citation` に追加:

```
spans: list[EvidenceSpan] = []      # 空 = 未特定
  ordinal: int      # 1 起算。UI では "3-1" と表示
  start: int        # chunk.text 上の文字オフセット
  end: int
  quote: str        # 表示・原本矩形検索に使う実文字列
```

既存の永続化済みメッセージには `spans` が無い。フロントは `spans` が空のとき**従来どおり
チャンク全文を素で表示**する(会話履歴は壊さない)。`snippet` は互換のため残すが、
UI からは参照しない。

### 3.3 表示 — バッジと本文ハイライト

- **バッジ** (`apps/web/src/lib/components/CitationBadge.svelte`, `apps/web/src/lib/utils/citations.ts`):
  黄色の丸 → 角丸タグ。ラベルは `3-1` 形式(`spans` が空のときは `3`)。
  選択中は塗り (`--color-evidence`)、非選択は淡色。
- **本文** (`apps/web/src/lib/components/SourceViewer.svelte`):
  `<pre>` の一括表示をやめ、スパン境界で分割して `<mark>` を挟む。ハイライトは**マーカー下線**
  (下 62% に薄い色を敷き、2px の下線)。選択中のスパンは濃く、同一チャンク内の他スパンは
  淡く表示する。選択中スパンへは自動スクロールする。
- **配色トークン** (`apps/web/src/app.css`): `--color-citation-bg` / `--color-citation-border`
  を廃止し、`--color-evidence: #3563e9` / `--color-evidence-soft` / `--color-evidence-faint`
  に置き換える。旧トークンの参照は `ChatMessage.svelte` / `CitationBadge.svelte` /
  `SourceViewer.svelte` の3ファイルのみ。

### 3.4 原本ページ表示 (PDF のみ)

出典パネル内に「テキスト / 原本 p.N」タブを設ける。パネル幅 (360px) は変更しない。

- **描画**: `core/sources/page_render.py`(新規)。PyMuPDF で該当ページを 150dpi の PNG に
  レンダリングし、`data/cache/pages/{source_id}/{page}@{dpi}.png` にディスクキャッシュする。
  **事前生成しない**(索引サイズ・ingest 時間を増やさないため)。
- **矩形**: `page.search_for(span.quote)` の戻り値をページ座標系の矩形として返す。
  複数ヒット時は全件返し、UI 側で選択中スパンに対応するものを濃く描く。
- **API** (`apps/api/routers/sources.py`):
  - `GET /api/sources/{source_id}/pages/{page}?dpi=150` → PNG
  - `GET /api/sources/{source_id}/pages/{page}/rects?chunk_id=&ordinal=` → 矩形 JSON
- **UI**: 青枠オーバーレイ、「拡大」(全画面)、前後ページ送り。360px では文字は読めない前提で、
  位置把握を目的とし、精読はテキストタブか拡大で行う。
- **出さない条件**: ソースが PDF でない、または元 PDF が見つからない場合はタブごと非表示。
  `search_for` が空振りした場合はページのみ表示し「枠は特定できません」と注記する。

### 3.5 選択範囲翻訳

- テキストタブで文字列を選択すると、選択範囲の近傍に小さな「訳」ボタンが浮く。押すと
  選択箇所の**直下に訳文をインラインで差し込む**(原文は消さない = 対訳で読める)。
  再クリックで畳む。
- **API** (`apps/api/routers/translate.py` 新規, `core/translation/translator.py` 新規):
  `POST /api/translate` `{text, target_lang, model?}` → SSE でトークンをストリーム。
  既存の Ollama クライアント (`core/ollama/`) をそのまま使う。
- **モデル**: `model` 未指定時はノートブックの現在のチャットモデルを流用する。
  設定 (`apps/api/schemas/settings.py`, `apps/web/src/routes/settings`) に翻訳専用モデル欄を
  追加し、指定があればそちらを使う。
- 選択が無いとき、原本タブ表示中はボタンを出さない。

### 3.6 β機能: LLM 引用抽出

[[005-beta-feature-flag-registry]] のフラグレジストリに `citation_quote_mode` を登録する。

- **ON**: 生成プロンプトに「各 `[^n]` の根拠となる原文を短く併記せよ」という指示を足し、
  応答から抽出した quote を**優先スパン**として使う(位置は quote の完全一致検索で確定)。
  quote が本文に見つからなければ §3.1 の字句照合にフォールバックする。
- **OFF (既定)**: プロンプト・生成経路は現行のままバイト単位で不変。
- 設定画面に「出力トークンが増え、応答が遅くなります」と明記する。効果の比較検証はこの
  トグルの ON/OFF で行う。

## 4. エラー処理

| 事象 | 挙動 |
|---|---|
| スパン未特定 | ハイライトなし・チャンク全文を素で表示。上部に「この主張の根拠箇所は特定できませんでした」と控えめに表示。バッジは枝番なし |
| 非PDF ソース | 原本タブを出さない |
| 元 PDF が消えている | 原本タブを出さず、テキストタブのみ |
| `search_for` 空振り | ページ画像は出し、枠は描かず注記する |
| ページ描画失敗 | タブ内にエラー文を出す。テキストタブは影響を受けない |
| 翻訳失敗 / Ollama 未起動 | トーストで通知し、インライン挿入は行わない |
| β ON で quote 未出力 | 静かに字句照合へフォールバック(ユーザー通知は不要) |

## 5. テスト

- **unit** (`tests/unit/`): スパン解決器 — 完全一致 / 言い換えで未特定 / 同一チャンク複数出現 /
  表 Markdown・コードブロック混在 / 全角半角と約物の揺れ / 正規化逆写像の境界。
  矩形算出 — 複数ヒット、空振り。
- **integration** (`tests/integration/`): ページ描画エンドポイントのキャッシュヒット、
  非PDF ソースでの 404、翻訳エンドポイントの SSE 形。
- **frontend unit** (`apps/web/tests/unit/`): 枝番採番、`<mark>` 分割描画、`spans` 空時の
  従来フォールバック。
- **実機スクリーンショット検証(必須)**: ハイライト表示 / 原本タブ / 翻訳インライン挿入の
  3画面を evaluator で撮る。自動テストの GREEN だけでは PASS としない。

## 6. 決めたこと(ADR ドラフト起票対象)

1. 根拠スパンは**生成後の字句照合**で解決する。文単位の再埋め込みも、コンテキストの文単位
   分割も行わない(索引・生成経路に触れないため)。
2. 原本ページ画像は**オンデマンド描画＋ディスクキャッシュ**とし、事前生成しない。
3. スパン未特定は**明示**し、近似ハイライトで代替しない([[016-pixel-native-explicit-failure]]
   の延長)。

## 7. 未解決事項

なし。
