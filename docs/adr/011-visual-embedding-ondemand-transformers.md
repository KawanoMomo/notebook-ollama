---
type: adr
title: 視覚埋め込みはOllama外(transformers)でオンデマンド実行する
summary: "Ollama非対応の視覚埋め込みをtransformers+extra依存で実行し、オンデマンドロード+アイドルアンロードで11GB VRAMと共存させる設計判断。"
aliases:
  - 視覚埋め込み実行基盤
status: approved
date: 2026-07-20
adr: 011
project: NotebookOllama
area: retrieval
category: external-dep
tags:
  - adr
related:
  - "[[2026-07-20-visual-embedding-index-design]]"
  - "[[010-visual-index-qdrant-rrf]]"
  - "[[017-torch-cuda-wheel-index]]"
---

# ADR-011: 視覚埋め込みはOllama外(transformers)でオンデマンド実行する

- **ステータス**: 承認
- **カテゴリ**: external-dep
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
  → **この判断は [[017-torch-cuda-wheel-index|ADR-017]] で覆された。** 下記「後日の訂正」を参照

## 後日の訂正 (2026-07-30 / ADR-017)

上記「CUDA index 導入は見送り」は **cu126 での測定に基づく判断であり、cu130 では
再現しなかった**。ADR-017 の実測では、同じ RTX 2080 Ti・同じ Ollama 常駐条件
(qwen2.5:14b 9.5GB 常駐、エンコーダ4.4GBと合わせて約13.9GB > VRAM 11.26GB)で
**0.358秒/ページ**、CPU(52.5秒)の約147倍だった。

この ADR は破棄せず残す。判断そのものは当時の測定に対して妥当であり、**「CUDAは常駐下で
遅い」という結論だけが後続の測定で否定された**という経緯自体が記録に値するため。

派生する訂正:

- 本 ADR が「CPUフォールバック運用が現実の既定」としてスレッド上限・バースト間休止などの
  負荷ノブを正当化した前提は、GPU 経路では成立しない
- ただし `build_cooldown_seconds`(既定10.0秒)だけは実装上デバイスを見ずページ間に挟まり、
  GPU でも効き続けることが 2026-08-02 の効果測定で判明した(約9倍の速度低下)。
  詳細と再測定値は [[2026-07-29-pixelrag-tile-index-design|Stage 4 設計書]] の「効果測定」節

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
