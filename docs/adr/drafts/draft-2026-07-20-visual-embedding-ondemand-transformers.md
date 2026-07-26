---
type: adr-draft
title: 視覚埋め込みはOllama外(transformers)でオンデマンド実行する
summary: "Ollama非対応の視覚埋め込みをtransformers+extra依存で実行し、オンデマンドロード+アイドルアンロードで11GB VRAMと共存させる設計判断。"
aliases:
  - 視覚埋め込み実行基盤
status: proposed
date: 2026-07-20
project: NotebookOllama
area: retrieval
category: 外部依存/リソース管理
tags:
  - adr
  - draft
related:
  - "[[2026-07-20-visual-embedding-index-design]]"
  - "[[draft-2026-07-20-visual-index-qdrant-rrf]]"
---

# ADR-draft: 視覚埋め込みはOllama外(transformers)でオンデマンド実行する

- **ステータス**: 提案(ドラフト・未採番)
- **カテゴリ**: 外部依存/リソース管理
- **日付**: 2026-07-20
- **出典**: 視覚埋め込みインデックス設計 `docs/specs/2026-07-20-visual-embedding-index-design.md`

## コンテキスト

Ollamaは画像埋め込みモデル(Qwen3-VL-Embedding等)に対応していないため、視覚埋め込みには「Ollama一本」原則の例外が必要。RTX 2080 Ti 11GBでチャットLLMと共存させる制約もある。

## 検討した選択肢

### A) transformers + `--extra visual` + オンデマンドロード/アイドルアンロード

- メリット: 必要な人だけが導入するオプション依存(recording extraと同型)。fp16で4〜5GBをロードし既定5分のアイドルで解放、チャットLLMとVRAM衝突を回避
- デメリット: 「Ollama一本」原則の例外が生まれる。初回クエリにロード時間(数秒)

### B) 常駐ロード

- メリット: クエリ遅延最小
- デメリット: 11GBでチャットLLMと同時常駐は不安定

### C) Ollama対応を待つ/独自サーバ化

- メリット: 原則維持
- デメリット: 実現時期不明で機能が塞がる。独自サーバは過剰

## 決定

A を採用する。例外は視覚埋め込みに限定し、`OcrEngine` 同様の抽象化でOllama側が対応した場合の回帰余地を残す。CUDA不可環境はCPUフォールバック(所要時間目安を表示)。

## 結果

(2026-07-26 実装・実機検証済み、PR: feature/visual-embedding)

- 実行基盤は決定どおり transformers スタックだが、素の AutoModel/AutoProcessor では
  Qwen3-VL の forward が input_ids を要求し画像単独埋め込みが組めなかった。モデルの
  正規API(`library_name: sentence-transformers`)である **SentenceTransformer.encode
  ベース**に変更。実モデル依存は `_TransformersBackend` 1クラスに隔離済み
- **PyPI の Windows 版 torch は CPU-only wheel**(torch 2.13.0+cpu)のため、fp16/CUDA
  前提だった spec §7 は CPUフォールバック運用が現実の既定になった
- CPUロードは **bfloat16**(チェックポイントのネイティブdtype)を採用。fp32 は常駐
  8-9GB+型変換ピークでサーバープロセスがOOM即死した(実機2回)
- オンデマンドロード+アイドルアンロードは lifespan 常駐の watchdog(60秒間隔)で
  発火。**in-flight ガード必須**: 1回の埋め込みが idle 閾値を超えるCPU環境では、
  開始時刻基準のidle判定だと計算中のバックエンドを解放してしまい、ページ毎の
  ロード/アンロードスラッシングが起きた(実機で20分にロード8回を観測→修正)
- 実測(RTX 2080 Ti機・CPU bf16・安全プロファイル=8スレッド+休止10秒):
  約95秒/ページ、50ページ完走、RSS 4.5GB一定。全力プロファイル(24スレッド)は
  53秒/ページだが **マシンごとBSOD(0x7F_8)** を2回誘発 → 既定値は安全側に設定
- CUDA検証(隔離venv・torch cu126): sm_75対応・fp16ロード4.26GB(spec予測どおり)
  だが、Ollamaチャットモデル常駐下ではWDDM共有メモリスピルで画像8.7〜20.4秒/枚と
  CPU fp32より遅い。**11GBでの同時常駐は不成立(spec §7の警告を実測確認)**。
  CUDA index 導入は見送り

## 教訓

- 埋め込みモデルは HuggingFace の `library_name` が示す正規APIから書くこと。素の
  AutoModel から始めて実機ゲートで直すのは二度手間だった
- 「アイドルアンロード」は必ず in-flight 実行数を追跡すること。idle判定の基準時刻
  だけでは長時間実行と区別できない
- 全コアAVX連続実行はPrime95級のストレス負荷であり、K付きCPU+XMP環境ではマシン
  安定性マージンを超えうる。負荷ノブ(スレッド上限・バースト間休止)は機能要件
- ハイブリッドCPU(P+E)ではバックグラウンドプロセスがEcoQoSでE-coreに寄せられ、
  推論スレッドがE-coreクラスタを飽和させてブラウザ背景処理と競合する(実機FB)。
  対策はEcoQoS解除(SetProcessInformation、**argtypes明示必須** — 既定のc_int
  変換では64-bit HANDLEが壊れERROR_INVALID_HANDLEで常に失敗)+少数スレッド。
  P/E均等混載はfork-joinの律速と帯域律速(bf16エミュはP/E同速)で意味がない
