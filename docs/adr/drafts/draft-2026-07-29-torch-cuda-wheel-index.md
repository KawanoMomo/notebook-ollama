---
type: adr-draft
title: visual extraのtorchはCUDAホイールインデックスに切替、CPUはフォールバックとして残す
summary: "--extra visualのtorchを`[[tool.uv.index]]`(cu130)+marker付き`[tool.uv.sources]`でwin32のみCUDAホイールにし、CPU専用ホイールに起因していた対症療法群を解消した設計判断。recording extraとの共存不可という代償を伴う。"
aliases:
  - torch CUDA化
status: proposed
date: 2026-07-30
project: NotebookOllama
area: retrieval
category: 外部依存/パッケージング
tags:
  - adr
  - draft
related:
  - "[[2026-07-29-pixelrag-tile-index-design]]"
  - "[[draft-2026-07-20-visual-embedding-ondemand-transformers]]"
---

# ADR-draft: visual extraのtorchはCUDAホイールインデックスに切替、CPUはフォールバックとして残す

- **ステータス**: 提案(ドラフト・未採番)
- **カテゴリ**: 外部依存/パッケージング
- **日付**: 2026-07-30
- **出典**: PixelRAG式タイル索引と検索戦略の選択 `docs/specs/2026-07-29-pixelrag-tile-index-design.md` §1.1, §8

## コンテキスト

Stage 4 の設計中に、Stage 3 で導入した `--extra visual` の torch が PyPI 既定の **CPU専用ホイール**であり、RTX 2080 Ti(11GB)が視覚埋め込みに一切使われていないことが判明した。`VisualSettings` に積み上がっていた `build_cooldown_seconds=10.0` / `cpu_threads=4` / `cpu_prefer_performance_cores=True` といったP-core分業・冷却期間の対症療法群は、すべてCPU推論を成立させるための後付けだった。タイル分割は1ページあたりの埋め込み回数を約3倍にするため、CPUのままでは比較実験が回らない。

## 検討した選択肢

### A) `[[tool.uv.index]]` + marker付き `[tool.uv.sources]` でwin32のみCUDAホイールを指定

- メリット: `uv lock` / `uv sync` の通常フローに乗る。CPU環境(非win32やCUDA非搭載機)は自動的にPyPI既定のCPU専用ホイールにフォールバックする(marker分岐)
- デメリット: PyTorchの専用インデックス(`download.pytorch.org`)からの解決になり、一部パッケージ(torchvisionのcu130エントリ)でhashメタデータが欠落する場合がある(実害なし、pytorch側の制約)

### B) CPU専用のまま、タイル分割の既定を落として着地する(spec §8.4 の縮退案)

- メリット: 依存変更なし、リスクゼロ
- デメリット: タイル分割の構築コストがページあたり約2倍(推定 約190秒/ページ)となり、比較実験が小規模ノートブックに限定される

### C) torch以外の軽量推論ランタイム(ONNX Runtime等)への切替

- メリット: CUDA版torchより依存が軽い可能性
- デメリット: `Qwen/Qwen3-VL-Embedding-2B` のONNX変換・検証コストが本Stageのスコープを超える

## 決定

A を採用する。実機ゲート4段(`torch.cuda.is_available()` / `get_arch_list()` にsm_75含有 / 実埋め込み1枚が例外なく完了 / ページ/秒とVRAMの実測)すべてを通過することを受入条件とし、通らなければ B の縮退に切り替える運用とする。

## 結果

(2026-07-30 実装・実機検証済み)

- 実機ゲート4段、cu130のまま全て通過(cu132フォールバック不要)。`torch 2.13.0+cu130` / `torchvision 0.28.0+cu130` / `arch_list` に `sm_75` あり / RTX 2080 Ti (7, 5) 認識
- **実測(3条件ベンチマーク)**: 条件A(GPU, Ollama非常駐)0.368秒/ページ / 条件B(GPU, `qwen2.5:14b` 9.5GB常駐)0.358秒/ページ / 条件C(CPU)52.485秒/ページ。**条件Bは条件Cより約147倍速い**。Stage 3 の「Ollama常駐下ではCUDAがCPUより遅い(WDDMスピル)」という以前のセッション記録上の判断は、少なくとも cu130 + 本構成では再現しなかった
- `build_cooldown_seconds` / `cpu_threads` / `cpu_prefer_performance_cores` はコード変更なしで自動的に無効化される(`device == "cpu"` 分岐内にあるため)。CPUフォールバック用としてそのまま残置した

### ⚠️ 重大な帰結: `recording` extra と CUDA 版 `visual` extra は同一 venv で共存できない

判断の代償として、実機検証(Task 15b)で以下が判明した。

- `core/accel/cuda_dll.py::_register_cuda_dll_dirs()` が **CUDA 12 系**の cudnn/cublas DLLディレクトリをプロセス検索パスに登録する。これは `core/recording/transcriber.py` の**モジュールレベル**(`_CUDA_DLL_REGISTERED = _register_cuda_dll_dirs()`)で実行される
- その後 torch(**cu130 = CUDA 13**)が cuDNN を呼ぶと `CUDNN_STATUS_SUBLIBRARY_VERSION_MISMATCH` で落ちる
- **最小再現**: 素のプロセスでは `torch.nn.functional.conv2d` がGPUで通る → `_register_cuda_dll_dirs()` を先に呼ぶと同じconv2dがFAIL
- インストール実体: `nvidia-cudnn-cu12 9.23.2.1` / `nvidia-cublas-cu12 12.9.2.10`(`recording` extra が pin)vs `torch 2.13.0+cu130`
- **Task 1 の実測(0.358秒/ページ等)は `visual` + `pdf` のみの環境で取ったもので、その条件では正しい。** その後 `recording` を足した環境で衝突が顕在化した

**したがって「GPU STT(faster-whisper)と GPU 視覚埋め込みは同一 venv で両立しない」ことを、この判断の代償として明記する。** 運用上は用途ごとにvenvを分けるか、どちらか一方をCPU実行にする必要がある。

### リスク(実現前の懸念、実測で解消)

Turing (sm_75) のカーネル同梱は実際に埋め込みを1枚流すまで確定しないという懸念があったため、上記の実機ゲート4段を定義して検証した。結果、懸念は的中せず全段階通過した。

## 教訓

- 「CPU専用ホイールが既定で入っている」という前提の誤りは、対症療法(cooldown/cpu_threads等の設定群)という形で顕在化していた。パフォーマンス関連の設定ノブが不自然に多いときは、その下にある依存関係の前提を疑う価値がある
- CUDAビルドへの切替は「動くようになる」だけでなく「他のCUDA依存コンポーネント(faster-whisper-cuda等)とプロセス内で衝突しうる」という新しいリスク軸を持ち込む。DLL検索パスへの副作用(モジュールインポート時のグローバルな環境変更)は、同一プロセスに複数のCUDA関連extraが載る構成で特に危険
