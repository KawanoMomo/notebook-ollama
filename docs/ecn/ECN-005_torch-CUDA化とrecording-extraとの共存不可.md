---
type: ecn
title: torch の CUDA ホイール化と recording extra との共存不可
summary: "uv の [[tool.uv.index]] + marker付き sources で torch を cu130 に切替え視覚埋め込みが147倍高速化した変更と、その代償として recording extra と同一venvで共存できなくなった制約。"
status: applied
date: 2026-07-30
project: NotebookOllama
area: platform
tags:
  - ecn
  - cross-project
related:
  - "[[017-torch-cuda-wheel-index]]"
  - "[[011-visual-embedding-ondemand-transformers]]"
  - "[[ECN-003_視覚埋め込み第2インデックスとRRF融合]]"
---

# ECN-005: torch の CUDA ホイール化と recording extra との共存不可

- **ステータス**: 適用済 (PR #27 内、2026-08-02 マージ)
- **種別**: 改善 (+ 制約の追加)
- **対象コミット**: `dd878fb`, `195431b`
- **影響ファイル**: `pyproject.toml`, `uv.lock`, `core/accel/cuda_dll.py`,
  `core/recording/transcriber.py`
- **横断価値**: **HIGH** — GPU 依存を持つ全プロジェクトに当てはまる

## コンテキスト

ECN-003 (Stage 3) は「CUDA は Ollama 常駐下で CPU より遅い」と結論し、
CPU 実行を既定にした。その結果、視覚索引の構築は **約95秒/ページ** で、
50ページの資料でも80分かかる実用性の低いものになっていた。

原因を追うと、**PyPI の Windows 版 torch は CPU-only wheel** (`torch 2.13.0+cpu`)
だった。「CUDA が遅い」以前に、**CUDA が使われていなかった**。

## 問題の詳細

### `pip install torch` では Windows で GPU が使えない

PyPI のデフォルト配信は CPU 版。GPU を使うには PyTorch 独自のホイール
インデックスを明示する必要がある。この事実に気づかないまま
「torch は入っている / `torch.cuda.is_available()` も見た」で進むと、
**遅い理由を推論やモデルの側に探し続けることになる**。

## 対策

### 1. uv のインデックス指定 (`dd878fb`)

```toml
[[tool.uv.index]]
name = "pytorch-cu130"
url = "https://download.pytorch.org/whl/cu130"
explicit = true

[tool.uv.sources]
torch = [{ index = "pytorch-cu130", marker = "sys_platform == 'win32'" }]
```

- `explicit = true` で、このインデックスは**明示的に指定したパッケージにしか
  使われない** (他の依存が巻き込まれない)
- `marker` でプラットフォームを限定し、**Linux/macOS のロックは壊さない**

### 2. 共存不可の明文化 (`195431b`)

CUDA 化の代償として、**`recording` extra と CUDA 版 `visual` extra は
同一 venv で共存できなくなった**。

**原因**: `core/accel/cuda_dll.py::_register_cuda_dll_dirs()` が
`nvidia-cudnn-cu12` / `nvidia-cublas-cu12` (**CUDA 12** 系) の DLL ディレクトリを
プロセスの検索パスに登録する。これは `core/recording/transcriber.py` の
**モジュールレベル**で実行されるため、recording extra が入っていれば必ず走る。
その後 torch (cu130 = **CUDA 13**) が cuDNN を呼ぶと
`CUDNN_STATUS_SUBLIBRARY_VERSION_MISMATCH` で落ちる。

**症状が分かりにくい**:

- `torch.cuda.is_available()` は **True のまま**なので CPU にフォールバックしない
- `core/visual/encoder.py` はロード時に一度デバイスを決めるだけで、CUDA 演算の
  失敗時に CPU へ落ちる経路が無い
- 結果は「遅くなる」ではなく **視覚インデックス構築の全ページ失敗**

**最小再現**:

```python
# 素のプロセスでは通る
torch.nn.functional.conv2d(x, w)          # OK (GPU)

# 先に DLL ディレクトリを登録すると同じ演算が落ちる
from core.accel.cuda_dll import _register_cuda_dll_dirs
_register_cuda_dll_dirs()
torch.nn.functional.conv2d(x, w)          # CUDNN_STATUS_SUBLIBRARY_VERSION_MISMATCH
```

## 結果

CUDA cu130、Ollama で 14B チャットモデル (9.5GB) を常駐させた状態で:

| 条件 | 秒/ページ |
|---|---|
| A: CUDA (チャットモデル非常駐) | 0.35 |
| B: CUDA (**qwen2.5:14b 常駐下**) | **0.358** |
| C: CPU (`CUDA_VISIBLE_DEVICES=""`) | 52.485 |

**条件Bは条件Aとほぼ同速** (誤差内)、CPU 比 **約147倍**。
エンコーダ 4.4GB + チャットモデル 9.5GB = 約13.9GB > VRAM 11.26GB で
**超過しているにもかかわらず速度劣化しなかった**。

ECN-003 の「常駐下では CPU より遅い」(cu126 で実測) は **cu130 では再現しなかった**。

### 運用上の使い分け

```bash
uv sync --extra visual --extra pdf     # GPU で視覚埋め込みを使う
uv sync --extra recording              # GPU で音声認識を使う
uv sync --all-extras                   # ❌ 視覚索引が壊れる
```

**注意**: `tests/unit` は recording extra 無しだと `soundfile` の import で
**収集ごと中断**する (`test_recording_pipeline_*.py` が `importorskip` 未使用)。
全体回帰を回す venv と GPU 視覚埋め込みを使う venv は分ける必要がある。

## 教訓

- **「GPU が使えている」は `torch.cuda.is_available()` では確認できない。**
  実際に演算 (`conv2d` 等) を1回通して、かつ**所要時間を測る**こと。
  今回は「CUDA が有効に見えて実際は CPU wheel」という状態で、
  性能問題の原因を1ステージ分 (ECN-003 全体) 誤診した
- **CUDA のメジャーバージョン混載は同一プロセス内で破綻する。** 複数の
  GPU ライブラリ (cuDNN / cuBLAS / ctranslate2 / torch) を同居させるときは、
  **どれがどの CUDA メジャー版を引くか**を先に確認する
- **`add_dll_directory` 相当をモジュールレベルで実行するのは危険。**
  import しただけでプロセス全体の DLL 解決が変わり、無関係な機能を壊す。
  遅延実行できるなら関数内に閉じ込めること
- **性能の判断は測定条件ごと記録する。** 「CUDA は遅い」だけを結論として残すと、
  条件 (cu126 / WDDM スピル) が変わったときに再検証されない
