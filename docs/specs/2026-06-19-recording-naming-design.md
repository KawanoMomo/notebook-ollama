---
type: spec
title: 録音の自動命名・ソース名編集
summary: "録音タイトルのLLM自動命名+全ソース名インライン編集、名前採用しきい値スライダー表示改善。"
aliases:
  - 録音命名
status: approved
status_inferred: true
date: 2026-06-19
project: NotebookOllama
area: recording
tags:
  - spec
code:
  - apps/api/routers/recordings.py
  - apps/api/routers/sources.py
  - apps/api/schemas/settings.py
  - apps/web/src/lib/api/sources.ts
  - apps/web/src/lib/components/SourceCard.svelte
  - apps/web/src/lib/components/SourcesPanel.svelte
  - apps/web/src/lib/components/settings/AudioSettingsSection.svelte
  - core/config.py
  - core/recording/recording_pipeline.py
  - core/recording/title_inference.py
  - core/storage/sources_repo.py
---

# 録音の自動命名・ソース名編集 + しきい値表示改善 設計仕様

> 対象バッチ: (a) 名前採用しきい値スライダーの値表示改善 / (c) 録音タイトルのLLM自動命名 + 全ソース名のインライン編集。
> 群2(#2 モデル選択 等)は本仕様の対象外(本バッチの後に着手)。

作成日: 2026-06-19 / ブランチ: `feature/recording-naming`(`feature/rag-ux-improvements` の上に積む。master 直接編集禁止)。

## 1. 目的
- 録音ソースが全て「録音」表示で区別できない問題を解消する。会議内容(トランスクリプト)から **LLM が簡潔なタイトルを自動予想**して設定し、気に入らなければ **UIから編集**できるようにする。
- 設定の名前採用しきい値が「0.65未満は相手Nのまま」と説明されるが値の所在が分かりにくいので、**スライダー現在値を説明文に埋め込み**一目で分かるようにする。

## 2. 決定事項(確定)
| 項目 | 決定 |
|---|---|
| (a) しきい値表示 | スライダー現在値は既に live 表示されている(故障なし)が分かりにくい。説明文を「**この値({値})未満は「相手N」のまま**」に変更し、値=しきい値だと明示する。 |
| (c) 自動命名 | 停止後パイプラインで、**整文済みトランスクリプトから LLM が 1 つのタイトル(全角20文字目安)を予想**して `source.title` に設定。設定 `auto_title`(既定 ON)で ON/OFF。OFF または セグメント0件なら従来どおり `title=None`(カードは「録音」表示)。**再生成(retry)時も同様に再命名**する。 |
| (c) 名前編集 | **サイドバーのソースカード上でインライン編集**。鉛筆アイコン(ホバー表示)クリックで題名がテキスト入力に変わり、Enter/blur で保存。**全 kind のソースに適用**(録音以外もリネーム可)。単一クリックの選択(ビューア表示)とは別トリガー。 |
| バックエンド rename | `PATCH /api/notebooks/{nb}/sources/{sid}` で `{title}` を更新し、更新後 `Source` を返す。空文字/空白のみは 422。 |

## 3. 機能別設計

### (a) しきい値表示改善
- 現状: `apps/web/src/lib/components/settings/AudioSettingsSection.svelte` の名前採用しきい値行は `<input type="range" bind:value={draft.name_threshold}>` + `<span class="mono">{draft.name_threshold.toFixed(2)}</span>` + `<span class="hint-text">未満は「相手N」のまま</span>`。値は live 更新される。
- 変更: ヒント文を「**この値未満は「相手N」のまま**」に変更(値は隣接の `.mono` が示す)。または mono とヒントを1文に統合し「**この値 ({draft.name_threshold.toFixed(2)}) 未満は「相手N」のまま**」。実装時に視認性の良い方を採用。純表示変更。
- 検証: 設定でスライダーをドラッグ → 数値が追従し、「この値未満は…」で意味が通ることをスクショ確認。

### (c-1) 録音タイトルの LLM 自動命名(バックエンド)
- 設定: `core/config.py AudioSettings` に `auto_title: bool = True` を追加。`apps/api/schemas/settings.py AudioSettingsSchema` + フロント `AudioSettings` 型 + 設定UIにトグル追加(「録音データの保存」または「話者分離/名前予想」グループ)。
- タイトル生成器: `core/recording/title_inference.py`(新規, name_inference.py に倣う)。
  - `build_title_prompt(segments) -> str`: 整文済みセグメントの本文を連結・先頭~一定文字数で打ち切り、「以下の会議の文字起こしから、内容を表す簡潔なタイトルを1つ、全角20文字程度で出力。タイトルのみ返す。」等のプロンプト。
  - `parse_title(raw) -> str`: 余分な引用符/前置きを除去し1行に。空なら "" を返す。
  - `async infer_title(segments, llm, model) -> str`: 上記を実行。例外時は "" を返す(致命的でない)。
- パイプライン結線: `core/recording/recording_pipeline.py RecordingPipeline.run`。`auto_title_enabled` 引数(既定 True)を追加。整文(correct)後・チャンク化前後のどこかで、`auto_title_enabled and corrected` のとき `infer_title` を呼び、得たタイトルを `source.title` に設定する。
  - タイトル保存: `core/storage/sources_repo.py` に `update_source_title(conn, source_id, title)` を追加(`UPDATE sources SET title=?, updated_at=? WHERE id=?`)。READY 更新とは独立に呼ぶ(失敗しても READY は進める=best-effort)。
  - SSE: タイトル設定後の `source_status` イベントに `title` を載せられるとフロントが即反映できる(任意。最低でも次の list/upsert で反映)。
- 結線元: `apps/api/routers/recordings.py` の stop と retry の dispatch(`_dispatch_recording_pipeline` 共有ヘルパ)に `auto_title_enabled=a.auto_title` を渡す。
- 検証(統合): fake LLM でタイトルが返るとき `source.title` が設定されること、auto_title=False または空セグメントで `title` が変わらないこと。

### (c-2) ソース名のインライン編集(全ソース)
- バックエンド: `apps/api/routers/sources.py` に `PATCH /{notebook_id}/sources/{source_id}`(body `{title: str}`)。所有チェック → `sources_repo.update_source_title` → `_to_schema(get_source(...), sources_dir)` を返す。空/空白のみは `INPUT_INVALID`(422)。
- フロント:
  - `apps/web/src/lib/api/sources.ts` に `rename(notebookId, sourceId, title) -> Source`。
  - `apps/web/src/lib/components/SourceCard.svelte`: タイトル横に鉛筆アイコン(ホバー表示)。クリックで `editing=true` → タイトル部を `<input>` に切替(現タイトル初期値)。Enter または blur で `onRename(s.id, value)` を呼ぶ。Esc でキャンセル。入力中はカード選択(onSelect)を発火させない(stopPropagation)。
  - `apps/web/src/lib/components/SourcesPanel.svelte`: `onRename` ハンドラ → `sourcesApi.rename` → `currentNotebookStore.upsertSource(updated)` + トースト。`SourceCard` に `onRename` prop を配線。
- 検証(視覚): 録音カードの鉛筆 → インライン入力 → 保存でカード名が変わること、リロード後も保持(永続化)を確認。文書ソースもリネームできることを確認。

## 4. 横断方針 / 非機能
- 新規ランタイム依存なし。LLM タイトル生成は既存 `OllamaGateway.generate` を流用。
- 自動命名は best-effort(失敗・空でも READY を阻害しない)。
- `auto_title` 既定 ON。設定で OFF 可(永続化は既存 settings.json 経路)。
- 既存テストを壊さない。新規バックエンドはユニット/統合テスト追加。GUI 変更は Playwright 実機検証ゲート。
- コミット trailer は付けない。

## 5. 対象外
- 群2(#2 モデル選択 / #3 保存先パス)、群3(#1 アクセラレータ / #9 リモート推論)。
- 声紋横断命名(Task 4.7)、duration_ms 配線。
