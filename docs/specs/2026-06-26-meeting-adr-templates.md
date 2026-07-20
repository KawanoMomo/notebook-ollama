---
type: spec
title: 議事録テンプレ + ADR 抽出機能
summary: "議事録用の要約テンプレとADR抽出専用テンプレ/ボタンを追加。"
aliases:
  - 議事録テンプレ
  - ADR抽出
status: approved
status_inferred: true
date: 2026-06-26
project: NotebookOllama
area: summary
tags:
  - spec
---

# 議事録テンプレ + ADR 抽出機能 — 設計仕様

> 作成: 2026-06-26
> ブランチ: `feature/meeting-adr-templates`
> 親ブランチ: `feature/summary-prompt-tune`

## 背景・要件

- ユーザ要望: 「議事録書き起こし用の[要約]テンプレートを用意してほしい。あとは ADR の専用ボタンのテンプレートを用意してほしい。」
- 既存の要約プロンプトは汎用ドキュメント用(Faithful-Compression)1 本のみ。
  録音(Whisper STT + 話者分離)に対して同じテンプレを使うと、決定/未解決/
  アクションの軸を取り損ねる。
- ADR は要約とは別概念(抽出 + Decision Gate)で、ボタン UX も別に欲しい。

## Deep Research 要点(workflow wf_3221e5c8-b6f, 2026-06-26)

### 議事録要約
- Faithfulness を最上位に置く(STT 誤認識・推測・固有名詞創作の抑制)
- 議事録特有の 3 軸: 決定事項 / 未解決の論点 / 次のアクション
  (intent / agency / temporality の推論)
- 話者の行動を中立記述(提案・合意・反対・保留・引き受け)。性格・感情の推定は禁止
- 雑談・フィラー・繰り返しを明示排除、ただし議題関連の脱線は 1 文で残す
- 文構成を 1文目/2-3文目/4-5文目 にスロット配分し、長尺会議で漏れを防ぐ
- 出典: arXiv 2407.11919, 2509.13814, 2307.15793, 2509.15901, Chain of Density

### ADR 抽出
- MADR 4.0.0 を既定。Considered Options が 1 件以下なら Nygard 自動ダウングレード
- **Decision Gate**(yes/no + 根拠引用): ADR にすべき決定が含まれるか先に判定。
  判定基準(2 つ以上満たす): (a) 選択肢比較, (b) 制約/トレードオフ言及,
  (c) 合意宣言(採用/決定/承認/Go/LGTM)
- 抽出ベース優先 + 推測は `<inferred>...</inferred>` で囲む / 該当なしは `<!-- TBD -->`
- 出力は YAML front-matter + Markdown 本文のハイブリッド
  (機械処理は front-matter、人間レビューは本文)
- 出典: https://adr.github.io/madr/, prompt engineering best practices 2026

## アーキテクチャ判断

| 質問 | 採択 | 根拠 |
|---|---|---|
| 要約テンプレを kind で分岐するか引数で受けるか | **kind 自動判定** | ソース取込時点で kind 確定済み、UX 価値なし、バグ防止 |
| ADR は SummaryJob と同居か別 | **別ジョブ AdrJob** | 4 状態(skipped 追加)/ 出力形式(Markdown + front-matter)/ 起動契機(ボタン)がすべて違う |
| ストレージ拡張は別表か列追加か | **sources 列追加** | 1 ソース ↔ 1 ADR、summary と同パターンで対称性、YAGNI |
| ADR API は明示 template 引数か | **無し(MVP)** | YAGNI、将来 `?template=madr|nygard` を後付け可 |
| UI ボタン配置 | **guide-head の右端、Refresh の隣に "ADR" バッジ付き** | 縦肥大化禁止原則、guide の文脈で並列 |

## モジュール構成

```
core/
  summary/
    summarizer.py          # _build_prompt() で kind 分岐(後方互換シグネチャ)
    prompts/
      __init__.py
      document.py          # 既存 Faithful-Compression テンプレを移管
      meeting.py           # NEW: 議事録テンプレ
  adr/                     # NEW パッケージ
    __init__.py
    adr_job.py             # AdrJob: Gate → Extract → publish/persist
    prompts.py             # build_gate_prompt / build_extract_prompt
  storage/
    schema.sql             # adr_draft / adr_status / adr_template /
                           # adr_confidence / adr_generated_at 追加
    migrations.py          # run_adr_migration (idempotent ALTER)
    sources_repo.py        # AdrStatus, update_source_adr_*, clear_source_adr

apps/api/
  routers/sources.py       # POST /adr (202), DELETE /adr (204)
  schemas/source.py        # Source に adr_* 5 fields 追加
  dependencies.py          # AdrJob 配線, ctx.adr_runner

apps/web/
  src/lib/api/types.ts     # AdrStatus, Source.adr_*
  src/lib/api/sources.ts   # generateAdr / deleteAdr
  src/lib/components/SourceCard.svelte  # ADR ボタン + ADR セクション
  src/lib/components/SourcesPanel.svelte # onGenerateAdr 配線
```

## SummaryJob の kind 自動分岐

```python
def _build_prompt(self, kind: str, chunks: list) -> str:
    if kind == "recording":
        return build_meeting_prompt(chunks, max_tokens=self._deps.max_input_tokens_meeting)
    return build_document_prompt(chunks, max_tokens=self._deps.max_input_tokens)
```

- `SummaryJob.run(source_id=...)` のシグネチャは変えない(後方互換)。
  内部で `sources_repo.get_source(conn, source_id)` から kind を取得済み。
- `SummaryDeps.max_input_tokens_meeting` の既定 = 8000(document の 4000 より長い)。

## AdrJob のフロー

```
run(source_id):
  1. chunks=list_chunks_for_source(...)
     no chunks → adr_status=ERROR, no LLM call
  2. adr_status=GENERATING + SSE publish
  3. Phase 1: Gate
       prompt = build_gate_prompt(chunks, max_tokens)
       gate_raw = llm.generate (3-retry)
       if YES → next
       if NO  → update_source_adr_skipped(reason, evidence) + SSE skipped
  4. Phase 2: Extract
       prompt = build_extract_prompt(chunks, max_tokens, summary_hint=src.summary)
       adr_raw = llm.generate (3-retry)
       template, confidence = parse_front_matter(adr_raw)
       update_source_adr(draft=adr_raw, template, confidence) + SSE ready
  5. 例外時: adr_status=ERROR + SSE error
```

## API

| Method | Path | 動作 | レスポンス |
|---|---|---|---|
| POST | `/api/notebooks/{nb}/sources/{src}/adr` | adr_status=generating にリセット、AdrJob を background 起動 | 202 + Source |
| DELETE | `/api/notebooks/{nb}/sources/{src}/adr` | adr_* 列を全て NULL | 204 |

Source schema(レスポンス)に以下を追加:
- `adr_draft: string \| null`
- `adr_status: 'generating' \| 'ready' \| 'error' \| 'skipped' \| null`
- `adr_template: string \| null`
- `adr_confidence: string \| null`
- `adr_generated_at: string \| null`

## UI

SourceCard の guide-head に **ADR ボタン**(FileCog アイコン + "ADR" バッジ)を追加。
要約再生成ボタンの右隣り。クリックで `onGenerateAdr` 発火 → API 起動 → ガイド自動展開。

ガイド本文の要約セクション下部に **ADR セクション**を追加。状態ごとに表示:
- `null` → 何も表示しない
- `generating` → スケルトン 4 行 + "ADR を抽出中…"
- `ready` → ADR ラベル + template + confidence バッジ + Markdown 全文 (`<pre>`)
- `error` → "ADR 抽出に失敗しました" (赤)
- `skipped` → "この資料には Architecture Decision が検出されませんでした (reason)"

ボタン disabled 条件(視覚的に薄く + cursor: not-allowed):
- `chunk_count === 0` (中身がない)
- `status !== 'ready'` (まだ取込中)
- `adr_status === 'generating'` (二重起動防止)

## テスト

| Sprint | 種別 | 件数 |
|---|---|---|
| S1 | pytest(マイグレーション・CRUD) | 8 |
| S2 | pytest(議事録テンプレ分岐) | 5 + 8 既存 |
| S3 | pytest(AdrJob 全フロー) | 7 |
| S4 | pytest(API ルーター) | 6 |
| S5 | vitest(SourceCard ADR) | 9 |
| 全体 | pytest 373 + vitest 81 | 全 GREEN |

## 視覚検証(S6)

`docs/eval/2026-06-26-meeting-adr/01-adr-five-states.png` に 5 状態(未生成 / generating /
error / skipped / ready)を 1 ページにまとめて Playwright で実機スクショ済み。

## 既知の制約 / 次フェーズ候補(本 MVP には含まない)

1. ADR と要約の同時実行による Ollama 過負荷 → asyncio.Semaphore で直列化を後で追加
2. gpt-oss 専用 `Reasoning: low/medium/high` のモデル名検出
3. Atomic-fact + NLI による自己批判ループ(評価ハーネス側)
4. 議事録長尺の map-reduce 要約(現状は先頭 8K tokens 切り捨て)
5. ADR の `.md` ダウンロード / クリップボードコピーボタン
6. 議事録 → ADR の 2 段階パイプ最適化(summary を hint に渡す部分は実装済み、ループは未実装)
