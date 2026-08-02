---
type: adr
title: pixel_native は根拠画像なしで黙って劣化させず明示エラーにする
summary: "pixel_native戦略でvision非対応モデル/根拠画像0枚のとき、AppErrorで明示的に失敗させる設計判断。専用SYSTEM_PROMPTとノートブック単位モデル上書き考慮を含む。"
aliases:
  - pixel-native明示失敗
status: approved
date: 2026-07-30
adr: 016
project: NotebookOllama
area: retrieval
category: error-handling
tags:
  - adr
related:
  - "[[2026-07-29-pixelrag-tile-index-design]]"
  - "[[009-vlm-ocr-ollama-only]]"
---

# ADR-016: pixel_native は根拠画像なしで黙って劣化させず明示エラーにする

- **ステータス**: 承認
- **カテゴリ**: error-handling
- **日付**: 2026-07-30
- **出典**: PixelRAG式タイル索引と検索戦略の選択 `docs/specs/2026-07-29-pixelrag-tile-index-design.md` §7.4

## コンテキスト

`pixel_native` 検索戦略は `RetrievedChunk.text` を空文字列にし、画像のみをVLMに渡す(プロンプト本文を持たせない)。この戦略で「vision非対応モデルが選択されている」「根拠画像が0枚しか集まらない」状況が起きたとき、どう振る舞うかの選定。

## 検討した選択肢

### A) 黙ってテキスト検索や既定戦略にフォールバックする

- メリット: ユーザーはエラーに遭遇しない
- デメリット: 本文がプレースホルダのみのソースからモデルが回答を作ってしまう(画像が届かないのに何らかの尤もらしい応答を返す)。ユーザーは「pixel-nativeで検証している」つもりが実は違う経路の結果を見せられ、Stage 2 のOCR品質ガードと同じ「無言の劣化」を繰り返すことになる

### B) `AppError` で明示的に失敗させる

- メリット: 「根拠なしの回答」というこのプロジェクトが最も避けたい失敗モードを構造的に防げる。Stage 2 で「11GB環境に実用OCRモデルが存在しない」ことを品質ガードで明示エラー化した判断と一貫する
- デメリット: pixel-nativeを試したいだけのユーザーが都度エラーメッセージに当たる。ただし復旧手段(vision対応モデルへの変更 / 戦略を戻す)をエラーメッセージに含めれば操作コストは低い

## 決定

B を採用する。`search_strategy == "pixel_native"` かつ選択中のチャットモデルが vision capability を持たない場合、`AppError(ErrorCode.INPUT_INVALID)` で失敗させる。

```
message:     pixel-native 検索には視覚対応のチャットモデルが必要です
remediation: 設定画面でチャットモデルを vision 対応のもの(qwen3-vl 系など)に
             変更するか、検索戦略を「視覚のみ」または「RRF融合」に戻してください。
```

判定には Stage 2 で実装済みの `probe_vision_capability` を再利用する。

既定の `SYSTEM_PROMPT` はルール1/3が「本文がプレースホルダのソースを扱う」前提の文言になっており、`pixel_native` にそのまま使うと「該当情報がありません」と誤答してしまう。そのため専用の `SYSTEM_PROMPT_PIXEL_NATIVE` を分けた。

## 結果

(2026-07-30 実装・実機検証済み)

- 決定どおり実装。実機検証(Task 15b)で、非vision対応モデル(qwen2.5:14b)選択時に「pixel-native 検索には視覚対応のチャットモデルが必要です」という明示的な日本語エラーが出ることを確認。vision対応モデル(gemma3:12b)では回答+引用+「添付画像を読み取って回答の根拠にしてください」の注記が返ることも確認した
- **実機で判明した追記**: vision 判定は**ノートブック単位の `default_model` 上書きを考慮する必要がある**。当初の実装(`apps/api/dependencies.py::_probe_vision`)は**グローバル** `config.ollama.default_model` だけを見ていたため、ノートブック単位で vision 対応モデルに上書きしていても誤って「視覚対応のチャットモデルが必要です」エラーになった(実機検証で不具合Bとして発見)。修正: `vision_check(model)` というシグネチャに変え、呼び出し元(`apps/api/routers/chat.py`)が `nb.default_model or ctx.config.ollama.default_model` で解決済みのモデル名を渡す形にした
- `vision_check` の内部で `probe_vision_capability` の呼び出しが失敗した場合(Ollama unreachable)は、`OLLAMA_UNREACHABLE` をそのまま再送出する。`INPUT_INVALID` に握り直すと「設定を変えろ」という誤った復旧行動をユーザーに提示することになるため、この握り直しはしない設計とした

## 教訓

- 「vision対応かどうか」のような判定は、グローバル既定値だけでなく「実際にそのリクエストで使われる値」を渡す関数シグネチャにしないと、機能横断の上書き機構(ノートブック単位のモデル上書き)と静かに矛盾する。設計時にコードだけレビューして見逃し、実機検証で初めて発見された
- エラーの再送出方針(握り直すか、そのまま伝播させるか)は「ユーザーがそのメッセージを見てどう行動するか」から逆算して決める。原因と無関係な復旧手順を提示するエラーコードへの握り直しは、かえって誤誘導になる
