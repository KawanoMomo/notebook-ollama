---
type: spec
title: Intel iGPU/NPU・AMD Ryzen AI 対応設計
summary: "Intel iGPU/NPU・AMD Ryzen AI対応。NVIDIA dGPU前提を緩和する設計。"
aliases:
  - アクセラレータ対応
  - iGPU/NPU
status: review
date: 2026-06-28
project: NotebookOllama
area: accel
tags:
  - spec
related:
  - "[[2026-06-19-model-selection-design]]"
code:
  - apps/api/main.py
  - core/accel/factory.py
  - core/accel/planner.py
  - core/accel/probe.py
  - core/config.py
  - core/ollama/client.py
  - core/recording/recording_pipeline.py
  - core/recording/transcriber.py
  - core/recording/whisper_postprocess.py
  - tests/integration/test_api/test_settings_acceleration.py
  - tests/perf/baseline.json
  - tests/perf/test_cuda_regression.py
---

# Intel iGPU/NPU・AMD Ryzen AI 対応設計

- 日付: 2026-06-28
- 対象リポジトリ: 10_NotebookOllama
- 種別: Design Spec (実装は別タスク。本書は仕様まで)
- ステータス: Draft, レビュー待ち
- 関連: `docs/specs/2026-06-19-model-selection-design.md` (モデル切替設計)

## 1. 背景と目的

現状の NotebookOllama は NVIDIA dGPU(CUDA + cuDNN)を強く前提にしている。
具体的には以下が NVIDIA がないと著しく劣化する/動かない。

- **ライブ字幕 (faster-whisper large-v3)**: `device="cuda"` 固定設定。GPU 失敗時 CPU/int8 にフォールバックするが、CPU では RTF が実用域を超え、5 秒 chunk x mic+system の二重ストリームに追随できない。
- **LLM (Ollama)**: Ollama 公式は CUDA 検出時のみ GPU で動作。Intel iGPU/NPU は標準では使われない。
- **bge-m3 embedding**: llama.cpp の GPU 経路に NaN bug([ollama#13572](https://github.com/ollama/ollama/issues/13572))があり、`num_gpu=0` で CPU 強制中。Intel iGPU/NPU で本来加速できる余地が眠っている。
- **話者分離 / 話者声紋 embedding (sherpa-onnx)**: ONNX Runtime の provider を `"cpu"` 固定。

近年は Intel Core Ultra (Meteor Lake / Lunar Lake / Arrow Lake) と AMD Ryzen AI (Phoenix / Hawk Point / Strix / Strix Halo / Krackan Point) が iGPU と NPU を統合し、ローカル AI ワークロードの主要対象になりつつある。本書はこれらの環境で NotebookOllama の主要機能を実用速度で動かす、ランタイム差し替え可能なバックエンド抽象化を定義する。

非目標:

- Apple Silicon / Linux / macOS 対応
- Snapdragon X (Hexagon NPU) 対応
- 既存 NVIDIA CUDA 経路の置換(温存して並走)
- 本書内での実装

## 2. ターゲットハードウェア

| ベンダ | 世代 | iGPU | NPU | 検出方法 |
|---|---|---|---|---|
| Intel | Meteor Lake (Core Ultra 100 系) | Arc Xe-LPG | NPU 3 | OpenVINO `Core().available_devices` |
| Intel | Lunar Lake (Core Ultra 200V) | Arc Xe2 (140V) | NPU 4 | 同上 |
| Intel | Arrow Lake (Core Ultra 200K/200H) | Arc Xe-LPG | NPU 3 | 同上 |
| AMD | Phoenix (Ryzen 7040) | Radeon 780M | XDNA 1 | `pnputil` PCI ID `VEN_1022&DEV_1502` |
| AMD | Hawk Point (Ryzen 8040) | Radeon 780M | XDNA 1 | 同上 |
| AMD | Strix Point (Ryzen AI 300) | Radeon 880M/890M | XDNA 2 | `VEN_1022&DEV_17F0&REV_00/10/11` |
| AMD | Strix Halo (Ryzen AI Max) | Radeon 8060S | XDNA 2 | 同上系 |
| AMD | Krackan Point (Ryzen AI 200/300) | Radeon | XDNA 2 | `VEN_1022&DEV_17F0&REV_20` |
| NVIDIA | RTX 全般 (現状資産) | — | — | `ctranslate2.get_cuda_device_count()` |

Windows 11 build 22621.3527 以上が前提 (Ryzen AI Software 1.7.1 の最低要件)。

## 3. アプローチ: マルチランタイム抽象化

「機能ごとに別々の最適ランタイムを選び、HTTP API 互換または Protocol で差し替える」案を採用。OpenVINO 一本化(AMD NPU 不対応)や環境別プロファイル(コード重複)は不採用。

### 3.1 アーキ全体図

```
[起動シーケンス]
HardwareProbe                  (新規 core/accel/probe.py)
  ├─ openvino.Core().available_devices
  ├─ pnputil /enum-devices /bus PCI /deviceids
  ├─ DXCore (DXCORE_HARDWARE_TYPE_ATTRIBUTE_NPU)     [補強用]
  └─ ctranslate2.get_cuda_device_count()
        ↓
HwProfile { vendor, dgpu, igpu, npu, vram_mb, ryzen_ai_gen,
            openvino_devices, has_directml }
        ↓
BackendPlanner                 (新規 core/accel/planner.py)
  入力: HwProfile + UserOverride (AudioSettings / OllamaSettings の既存項目を拡張)
  出力: BackendPlan {
      stt:           ベース実装名 + デバイス指定
      diarize:       同上
      speaker_embed: 同上
      llm:           Ollama endpoint URL + バックエンド名(表示用)
      text_embed:    OpenVINO 直 / Ollama URL のいずれか
  }
        ↓
BackendFactory                 (新規 core/accel/factory.py)
  Plan から Protocol 実装を生成して既存コアに注入
  ├─ Transcriber Protocol      ←  既存 Transcriber を Protocol 化
  ├─ Diarizer    Protocol      ←  既存 (diarizer.py) — 実装追加のみ
  ├─ SpeakerEmbedder Protocol  ←  既存 SpeakerEmbedder を Protocol 化
  ├─ TextEmbedder Protocol     ←  新規 (OllamaGateway 並走)
  └─ OllamaGateway             ←  URL 差替で透過 (公式 / IPEX-LLM Portable)
                                  または _ClientLike を満たす別 Client を注入
```

### 3.2 設計原則

- **既存コアコード非変更**: `apps/api/`、`core/recording/recording_pipeline.py` などの呼び出し側は Protocol しか触らない。実装の追加で動作が増える。
- **CUDA 経路は温存**: Planner が `faster-whisper-cuda` を選んだら現状と等価。今のユーザ(NVIDIA)に影響しない。
- **HTTP 互換最優先**: LLM/Embedding は Ollama HTTP API を共通契約として残す。URL 差替が一級手段。
- **オプトイン extras**: コア依存は今のまま。Intel/AMD ユーザは `uv sync --extra intel` / `--extra amd` で必要ランタイムを取る(後述)。
- **ユーザ override 可**: 自動検出を信頼しすぎない。設定画面に「手動上書き」セクションを必ず置く。

## 4. コンポーネント別バックエンド表

### 4.1 STT (Whisper)

| バックエンド ID | 対象 HW | extras | 想定モデル | 想定 RTF (目安) | 出典 |
|---|---|---|---|---|---|
| `faster-whisper-cuda` (現状) | NVIDIA dGPU | (既定) | large-v3 FP16 | ~0.1 | 既存実測 |
| `faster-whisper-cpu` | フォールバック | (既定) | medium int8 | ~0.8 | 既存 |
| `openvino-whisper-igpu` | Intel iGPU(Arc/Xe-LPG/Xe2) | `intel` | distil-whisper-large-v3 INT8 | ~0.3 (推定) | [Optimum Intel Inference](https://huggingface.co/docs/optimum/intel/openvino/inference) |
| `openvino-whisper-npu` | Intel NPU 3/4 | `intel` | distil-whisper-large-v2 INT8 (static shape) | ~0.4 (推定) | OpenVINO GenAI (`OVModelForSpeechSeq2Seq`) |
| `amd-whispercpp-npu` | AMD Ryzen AI NPU (XDNA1/2) | `amd` | large-v3 (encoder=NPU, decoder=CPU) | ~0.4 (推定) | [Ryzen AI whisper.cpp](https://ryzenai.docs.amd.com/en/latest/whisper_cpp.html) |

**選定原則**:

- NVIDIA: 現状維持 (`faster-whisper-cuda`)。
- Intel: NPU > iGPU > CPU。ライブ字幕は 5 秒固定 chunk が既に static shape 制約と整合する。
- AMD: Ryzen AI NPU > CPU。AMD は OpenVINO 非対応のため `amd/whisper.cpp` 公式 fork を採用。NPU はエンコーダのみ、デコーダは CPU(これは AMD 側の制約)。
- すべて失敗時は `faster-whisper-cpu medium int8`。

**Whisper モデルポリシー**:
バックエンドごとに「常用モデル」を別表で管理する。Intel NPU は静的形状制約のため distil-whisper-large-v2 を採用(CNN 部分が静的化しやすく検証事例が多い)。CUDA は large-v3 を維持。品質差は UI に明示する(§7.2)。

### 4.2 話者分離 + 話者声紋 embedding (sherpa-onnx)

| バックエンド ID | EP | 対象 HW | extras |
|---|---|---|---|
| `sherpa-onnx-cpu` (現状) | CPU | 全環境 | (既定) |
| `sherpa-onnx-dml` | `DmlExecutionProvider` | Intel/AMD iGPU 両方 | `intel` または `amd` (どちらも onnxruntime-directml) |
| `sherpa-onnx-openvino-gpu` | `OpenVINOExecutionProvider`, device=`GPU` | Intel iGPU | `intel` |
| `sherpa-onnx-openvino-npu` | 同上 device=`NPU` | Intel NPU | `intel` (非対応 op は CPU 自動 fallback、出典: [ONNX Runtime OpenVINO EP](https://onnxruntime.ai/docs/execution-providers/OpenVINO-ExecutionProvider.html)) |

`sherpa_onnx.OfflineSpeakerSegmentationModelConfig` と `SpeakerEmbeddingExtractorConfig` に `provider=` を渡す形(既存実装で `provider="cpu"` ハードコード箇所を Plan から差替え)。Embedding 側はモデルが小さいため iGPU 化の利得が小さい可能性があり、Planner は「Diarizer と同じ EP」を選ぶ(整合性優先)。

代替検討: ONNX Runtime EP で動かないモデルが見つかった場合は `pyannote-onnx-extended` への乗り換えを検討する(範囲外、将来課題)。

### 4.3 LLM (Ollama HTTP 互換 + 直叩き)

| バックエンド ID | 経路 | 対象 HW | extras |
|---|---|---|---|
| `ollama-cuda` (現状) | 公式 Ollama (`http://localhost:11434`) | NVIDIA dGPU | (既定、外部 Ollama 必須) |
| `ipex-llm-ollama` | IPEX-LLM Ollama Portable Zip 起動の `http://localhost:11434` | Intel iGPU/dGPU | `intel-ollama` 初回 ZIP DL+解凍(scripts/install-intel-ollama.ps1) |
| `ollama-vulkan` | 公式 Ollama Vulkan ビルド (将来) | AMD iGPU / Intel iGPU 双方 | 同上(代替) |
| `openvino-genai-server` | カスタム adapter (`OVGenAIClient` が `_ClientLike` Protocol を満たす) | Intel NPU(短いコンテキスト) / iGPU | `intel-genai` |

**重要**: 公式 Ollama / IPEX-LLM Ollama Portable は **同じポート同じ HTTP API**。差替は `OllamaSettings.endpoint` の URL 変更のみで完結し、`core/ollama/client.py` を一切変更しない。これがアプローチの最大の利得。

OpenVINO GenAI は Ollama API 非互換のため、`OllamaClient` と並ぶ `OVGenAIClient` を新規実装し、`_ClientLike` Protocol (既存) を満たす。`OllamaGateway` の `_client` 注入だけで透過的に差替可能。

**IPEX-LLM の継続性リスク**: [intel/ipex-llm](https://github.com/intel/ipex-llm) は 2026-01-28 にアーカイブ済 (read-only)。配布物 (Portable Zip) は引き続き使えるが、新規モデル対応や脆弱性修正は止まる。本書では「現時点で動く資産として採用、将来は OpenVINO GenAI への移行余地を確保」とする。Lunar Lake / Arc 140V で qwen3:8b Q4_K_M ~17-18 tok/s (出典: [TechHara Medium](https://medium.com/@techhara/local-llm-benchmark-on-intel-lunar-lake-133c39f10455))。

**NPU の制約**: NPU 上で LLM を動かす場合、コンテキスト長と同時実行に厳しい制約がある(static reshape、KV cache サイズ固定)。NotebookOllama の RAG では context budget 0.8 倍まで使う設計なので、NPU LLM はデフォルト無効、上級者向け opt-in にとどめる。

### 4.4 Text Embedding (bge-m3)

| バックエンド ID | 経路 | 対象 HW | 備考 |
|---|---|---|---|
| `ollama-bge-m3-cpu` (現状) | Ollama API `/api/embeddings` + `num_gpu=0` | 全環境 | NaN bug 回避中 |
| `ollama-bge-m3-gpu` | Ollama API (公式バグ FIX 後) | NVIDIA/AMD | [#13572](https://github.com/ollama/ollama/issues/13572) 状態監視 |
| `openvino-bge-m3-igpu` | Optimum Intel `OVModelForFeatureExtraction` device=`GPU` | Intel iGPU | 直接 Python 呼出 |
| `openvino-bge-m3-npu` | 同上 device=`NPU` | Intel NPU | static reshape 必要 |

OpenVINO 経路は Ollama を介さないため `TextEmbedder` Protocol を新設し、`OllamaGateway.embed()` の上位でラップする。Planner が OpenVINO 経路を選んだ場合は Gateway は呼ばれず、新規 `OpenVINOTextEmbedder` が呼ばれる。bge-m3 は OpenVINO 2026.0 で NPU 対応が強化された(出典: [Phoronix Intel OpenVINO 2026.0](https://www.phoronix.com/news/Intel-OpenVINO-2026.0-Released)、[Optimum Intel 2.0 blog](https://huggingface.co/blog/jeffboudier/optimum-intel-v2))。

## 5. データフロー

### 5.1 起動シーケンス

```
1. AppConfig 読込 (既存)
2. HardwareProbe.run()              [新規]
     OpenVINO devices → ["CPU","GPU","NPU"] etc.
     pnputil PCI dump  → AMD NPU 世代
     DXCore enumerate  → NPU 補強
     CUDA check
3. HwProfile 構築                    [新規]
4. SettingsStore.get_user_overrides()
5. BackendPlanner.plan(HwProfile, overrides) → BackendPlan
     (overrides に "auto" が入っていれば Planner 判定、それ以外は強制)
6. BackendFactory.build(Plan)
     Transcriber / Diarizer / SpeakerEmbedder / TextEmbedder / OllamaGateway を構築
     IPEX-LLM Ollama を使う場合は子プロセス起動 (PortableZip 内 ollama.exe)
7. FastAPI app に DI                 (既存の dependencies.py 経由)
```

### 5.2 ライブ字幕実行時

既存フロー(`LiveCaption.accept → _pop_chunk → transcribe_array`)は **そのまま**。`Transcriber` の差替で挙動が切り替わる。

- 5 秒 chunk x mic+system の二重ストリーム並列性は変わらない
- 既存の `_serial_lock` (mic/system 直列化) はそのまま機能する(セッション安全性は実装側で担保)
- バックエンドごとの「実効モデル名」と「effective device」は LiveCaption からも引けるようにする(既存の `effective_device` プロパティを Protocol に昇格)

### 5.3 PartialFailure と Graceful Degradation

`BackendFactory.build()` が機能単位で失敗を許容する。たとえば「STT は NPU で起動成功、Diarizer は OpenVINO EP 起動失敗」のとき、Diarizer だけ CPU フォールバックして全体は起動する。失敗ログは startup-banner に表示し、設定画面に「現在の各機能の effective backend」を可視化する(§7.1)。

## 6. エラー処理とフォールバック

### 6.1 フォールバック階層

各機能で次の階層を順に試す。

```
STT       NPU優先  → iGPU → CPU
LLM       URL 接続失敗 → 既存 OllamaClient へ戻す → エラー表面化
Diarizer  指定 EP → CPU
Embedder  指定経路 → Ollama (num_gpu=0) → CPU
```

LLM だけは「ローカルで自動切替」しない。理由: ユーザが選んだバックエンドが落ちた場合、もう一方を黙って使うとレスポンス品質と速度が大きく変わり、UX を破壊する。明示的なエラー表示で止める。

### 6.2 起動時自己検査

Planner で選んだバックエンドそれぞれに対し、ダミー入力 (1秒の zeros 音声 / "ping" embed 1 件 / "hi" chat 1 token) を投げる Smoke Test を `BackendFactory.build()` の末尾で実行する。失敗したものはフォールバック適用。

### 6.3 NPU プロセス分離(検討事項)

NPU は単一プロセスのみが占有できる(複数モデル同時実行が不安定)実例が IPEX-LLM Ollama でも観測されている(`OLLAMA_NUM_PARALLEL=1` 強制、5 分でモデル解放)。本書のスコープでは「同一プロセスで NPU を使う機能は STT *または* LLM の片方に絞る」をデフォルトとし、Planner がこれを保証する。

## 7. UI と運用

### 7.1 設定画面拡張

`apps/web/` の Settings に「Acceleration」タブを新設する。表示項目:

```
┌─ Hardware ─────────────────────────────────────────┐
│ Detected:                                          │
│  GPU       NVIDIA RTX 2080 Ti (CUDA 12.6)          │
│  iGPU      (none)                                  │
│  NPU       (none)                                  │
│  CPU       Intel i9-12900KF                        │
│                                                    │
│  [Re-detect]                                       │
└────────────────────────────────────────────────────┘

┌─ Backend Plan ─────────────────────────────────────┐
│ Mode  ○ Auto  ● Manual                             │
│                                                    │
│ STT          [faster-whisper-cuda  ▼]   effective: cuda
│ Diarize      [sherpa-onnx-cpu       ▼]   effective: cpu
│ LLM          [ollama-cuda           ▼]   effective: cuda
│ Embedding    [ollama-bge-m3-cpu     ▼]   effective: cpu
│                                                    │
│   [Test backends]    [Apply]                       │
└────────────────────────────────────────────────────┘
```

- ドロップダウンは検出 HW から実行可能な選択肢のみを表示
- "effective" は実際の起動結果(自己検査後)
- Re-detect / Test backends は同期実行(モデルロードが走るので進捗表示)
- "Apply" 時のみ FastAPI 側を再起動(コア再構築)

### 7.2 モデル品質差の表示

「バックエンドごとに適切なモデル」方針を取るため、ライブ字幕パネルや設定画面に effective model を必ず表示する。
例: `STT: openvino-whisper-igpu / distil-whisper-large-v3-int8`

### 7.3 ランタイムインストール手順

`scripts/install-intel-runtimes.ps1` と `scripts/install-amd-runtimes.ps1` を提供する想定。本書ではコマンドは規定しないが、最低限の責務:

- Intel: `uv sync --extra intel` を内部で呼び、IPEX-LLM Ollama Portable Zip を `$env:LOCALAPPDATA\notebook-ollama\runtimes\` に展開
- AMD: `uv sync --extra amd` と amd whisper.cpp バイナリ展開
- 完了後に NotebookOllama を再起動するよう促す

## 8. テスト戦略(実機なし前提)

### 8.1 CI で守る範囲

実機 iGPU/NPU は CI に存在しないので、ロジック層の保護に集中する。

- **HardwareProbe**: `openvino.Core` `pnputil` `DXCore` `ctranslate2` を全部モックし、表に挙げた全 HW プロファイルを再現する単体テストを置く(parametrize)。
- **BackendPlanner**: `HwProfile + UserOverride → BackendPlan` の表駆動テスト。HW 全組合せ x 自動/手動 x 失敗注入。**Planner にハード依存を持たせない**(probe を別モジュールに分離する重要動機)。
- **BackendFactory**: Protocol 実装の登録漏れがあれば import 時に検出する registry テスト。
- **Smoke Test**: 各 backend ID に対し「ダミー入力 → 1サンプル」が回ることを `pytest -m runtime` でゲート。CPU 経路のみ常時、ほかは marker でスキップ。

### 8.2 実機検証(ユーザ依頼ベース)

実機が手元にない前提で、テスタに依頼する形のテンプレを `docs/testing/igpu-npu-acceptance.md` (本書とは別ファイル、将来作成)に置く。最小ケース:

| ケース | 環境 | 検証内容 |
|---|---|---|
| AC-INTEL-1 | Core Ultra 100/200 + NPU drv | HardwareProbe が NPU を検出する |
| AC-INTEL-2 | 同上 | STT が `openvino-whisper-npu` で起動し、5 秒の発話を字幕化 |
| AC-INTEL-3 | 同上 | LLM が `ipex-llm-ollama` で qwen2.5:7b を回し、生成が始まる |
| AC-AMD-1 | Ryzen AI 300 シリーズ | HardwareProbe が pnputil で AMD NPU を検出する |
| AC-AMD-2 | 同上 | STT が `amd-whispercpp-npu` で起動し、5 秒の発話を字幕化 |
| AC-CUDA-REGRESSION | RTX 2080 Ti | Planner が `faster-whisper-cuda` を選び、現状と同等の RTF が出る |
| AC-CPU-FALLBACK | 何の GPU もない VM | すべて CPU 経路で起動し、ライブ字幕が(遅くても)動く |

GUI スクショは Memory ルール上必須。Evaluator が settings 画面の「Detected/effective」を撮る。

### 8.3 受け入れ基準

実装スプリント完了時に満たすべき機能要件:

- 既存 NVIDIA ユーザに動作回帰なし(AC-CUDA-REGRESSION)
- Intel Core Ultra ユーザがインストール手順実行のみで iGPU 経路まで自動到達 (AC-INTEL-1, 2, 3)
- AMD Ryzen AI ユーザが同様に NPU 経路まで到達 (AC-AMD-1, 2)
- 設定画面で手動上書きが効く(全プラットフォーム)

## 9. 依存と extras

`pyproject.toml` に `[project.optional-dependencies]` を追加する想定。

```
[project.optional-dependencies]
intel = [
  "openvino>=2026.0",
  "optimum[openvino]>=2.0",
  "onnxruntime-openvino",
  "onnxruntime-directml",
]
amd = [
  "onnxruntime-directml",
  "pywhispercpp",
]
nvidia = [
  # 既存依存(明示)
]
```

`intel-ollama` extra ではなく、ZIP は scripts 側で取得する(pip パッケージとして提供されていないため)。

## 10. リスクと未確定事項

| # | リスク / 不確定 | 影響 | 対応方針 |
|---|---|---|---|
| R1 | IPEX-LLM がアーカイブ済 ([intel/ipex-llm](https://github.com/intel/ipex-llm)) | 新モデル / 脆弱性パッチ停止 | OpenVINO GenAI への移行余地を残す。本書では Ollama API 互換性のみ依存し、内部実装は問わない |
| R2 | NPU の static shape 制約 | distil-whisper / bge-m3 を別途準備 | バックエンド別モデルポリシーで吸収。設定画面に effective model 明示 |
| R3 | sherpa-onnx の provider 切替が一部モデルで非対応 op | NPU で完全動作しない可能性 | OpenVINO EP は自動 CPU fallback。Smoke test で検出 |
| R4 | Ollama 公式 bge-m3 NaN bug が未解決の場合 | Embedding GPU 化が CUDA でも止まる | 現状の `num_gpu=0` を CUDA でも継続。OpenVINO 経路で別途解決 |
| R5 | 実機が手元にないため、推定 RTF が外れる可能性 | 期待品質に届かないバックエンドが採用される | Smoke test に最低性能ゲートを置き、未達なら次優先へフォールバック(階値は実機検証後に決定) |
| R6 | NPU 単一プロセス占有問題 | STT と LLM の同時 NPU 利用ができない | Planner が「NPU を割り当てる機能はひとつに絞る」をデフォルトに |

## 11. 範囲外 (Out of Scope)

- 本書での実装(別タスク)。本書は仕様まで。
- Linux / macOS / Snapdragon X 対応
- Whisper 以外の STT(Voxtral 等)
- LLM の量子化レシピ詳細(モデル別の Q4/Q5/AWQ 等の選定)
- 多重 GPU(NVIDIA dGPU + Intel iGPU 同時利用)

## 12. 出典

- [Ryzen AI Software whisper.cpp documentation](https://ryzenai.docs.amd.com/en/latest/whisper_cpp.html)
- [Ryzen AI Software installation requirements](https://ryzenai.docs.amd.com/en/latest/inst.html)
- [intel/ipex-llm (archived 2026-01-28)](https://github.com/intel/ipex-llm)
- [IPEX-LLM Ollama Quickstart](https://github.com/intel/ipex-llm/blob/main/docs/mddocs/Quickstart/ollama_quickstart.md)
- [ONNX Runtime OpenVINO Execution Provider](https://onnxruntime.ai/docs/execution-providers/OpenVINO-ExecutionProvider.html)
- [Optimum Intel Inference docs](https://huggingface.co/docs/optimum/intel/openvino/inference)
- [Optimum Intel 2.0: OpenVINO-First Toolkit](https://huggingface.co/blog/jeffboudier/optimum-intel-v2)
- [Phoronix: Intel OpenVINO 2026.0 Released](https://www.phoronix.com/news/Intel-OpenVINO-2026.0-Released)
- [DXCore enumeration APIs](https://learn.microsoft.com/en-us/windows/win32/dxcore/dxcore-enum-adapters)
- [Ollama bge-m3 NaN bug](https://github.com/ollama/ollama/issues/13572)
- [TechHara: Local LLM Benchmark on Intel Lunar Lake](https://medium.com/@techhara/local-llm-benchmark-on-intel-lunar-lake-133c39f10455)

---

## Update 2026-06-29 — Phase 1 split, scope reductions, and critical fixes

本書 §1〜§12 は当初設計のまま保持する(歴史的記録)。実装は以下の addendum を **正** として扱う。本 addendum はユーザ決定と adversarial review 指摘を反映したスコープ縮小・実装順の確定・致命的バグ修正を記録する。

### A. Phase 1 / Phase 2 への分割(ユーザ決定 1, 2)

実装プランは `docs/superpowers/plans/2026-06-29-igpu-npu-acceleration.md` で **Phase 1(Sprint 1〜3 / ~14 タスク)** に圧縮された。

**Phase 1 で出荷するもの**:

- `HardwareProbe` + `HwProfile`(全ベンダ検出、モック parametrize 単体テスト完備)
- `BackendPlanner` + `BackendPlan`(純関数、Intel/AMD 分岐も含む全 HW 表駆動テスト完備)
- `BackendFactory` skeleton(Phase 1 builder は CUDA + CPU 系のみ。Phase 2 ID は `NotImplementedError` で明示エラー)
- `core/recording/whisper_postprocess.py`(C2 fix の extract refactor。下記 D 参照)
- `core/config.py` への backend override フィールド追加(`"auto"` 既定、後方互換)
- `apps/api/main.py` lifespan で probe → planner を実行し `ctx.hw_profile` / `ctx.backend_plan` に格納(既存 `ctx.transcriber` 等の構築は Phase 1 では触らない)
- `GET /api/settings/acceleration`(read-only、診断用)
- フロント `AccelerationPanel.svelte`(**read-only、`<select>` も `[Apply]` も無し**。下記 E 参照)
- `tests/perf/baseline.json` + `tests/perf/test_cuda_regression.py`(下記 F 参照)
- `pyproject.toml` の `intel` / `amd` extras 空グループ(構造のみ、Phase 2 で充填)

**Phase 2 で出荷する予定のもの(無期限延期)**:

- `OpenVINOWhisperTranscriber`(Intel iGPU/NPU STT)
- `TextEmbedder` Protocol + `OpenVINOTextEmbedder`
- `RuntimeSupervisor`(IPEX-LLM Ollama Portable Zip 子プロセス起動)
- Acceleration タブの override UI(`<select>` + `Apply`)
- `PUT /api/settings/acceleration` と `BackendFactory.rebuild_in_place(ctx, plan, cfg)`
- `scripts/install-intel-runtimes.ps1`(IPEX-LLM Ollama Portable Zip 取得・展開を含む)
- `scripts/install-amd-runtimes.ps1`(**DirectML 経路のみ**。下記 B 参照)
- `pyproject.toml` の `intel` / `amd` extras 中身を実パッケージで充填

**Phase 2 着手前提条件**: 開発機が現状 NVIDIA RTX 2080 Ti のみ・Intel iGPU/NPU/AMD Ryzen AI 調達予定なしのため、Phase 2 は **事実上無期限延期**。実機(購入 / 借用 / 外部テスタ協力)が確保され次第着手する。

### B. AMD Ryzen AI NPU 用 Whisper を v1 から完全削除(ユーザ決定 3)

`amd-whispercpp-npu` は `BACKEND_IDS`・Planner・テスト・Phase 2 deferred の Sprint 4 タスク・インストールスクリプトのすべてから **削除** した(grep で 0 件)。AMD ユーザは Phase 2 着手後も DirectML 経路(`onnxruntime-directml`)のみで対応する。理由:

- `pywhispercpp` + AMD `whisper.cpp` 公式 fork の継続性リスク
- AMD NPU 実機が開発機に無く、モデル品質検証コストが見合わない
- DirectML 経路があれば NPU 経路無しでも実用速度に到達する見込み

### C. sherpa-onnx GPU/NPU provider 切替を v1+v2 共に descope(ユーザ決定 4)

当初設計の §4.2(`sherpa-onnx-dml` / `sherpa-onnx-openvino-gpu` / `sherpa-onnx-openvino-npu`)は **`BACKEND_IDS` から完全削除** し、Phase 2 でも実装しない。話者分離 + 話者声紋 embedding は **全環境(NVIDIA / Intel / AMD)で CPU 固定** となる(既知制約)。

理由:

- `sherpa-onnx` の provider 切替 API が一部モデルで非対応 op を持ち、実機検証コストが高い
- 話者分離 / 声紋 embedding は STT に比べて計算量が小さく、CPU でも体感への影響が限定的
- リファクタの blast radius を下げて Phase 1 を確実にデリバリすることを優先

`docs/testing/igpu-npu-acceptance.md` に「sherpa-onnx は全環境 CPU 固定」を **既知制約** として明記済み。

### D. 致命的修正 C1 — `probe_cuda()` の DLL search path 注入順序

**症状**: `uv` 経由で起動した clean Python から `core.accel.probe.probe_cuda()` を呼ぶと、`cudnn_ops_infer64_8.dll` が見つからず `ctranslate2.get_cuda_device_count()` が 0 を返し、Planner が **黙って CPU 経路を選ぶ**。ユーザ視点では「なぜか CUDA が効かない」状態に陥り、AC-CUDA-REGRESSION が silent fail する。

**根本原因**: `core/recording/transcriber.py` 内には既存 `_register_cuda_dll_dirs()` ヘルパが存在するが、これは `Transcriber.__init__` で初めて呼ばれる。Probe 経路はこのヘルパを通らないため、CUDA が不可視のまま `import ctranslate2` してしまう。

**Fix**: `probe_cuda()` は `import ctranslate2` の **前** に必ず `_register_cuda_dll_dirs()` を呼ぶ(Phase 1 Sprint 1 Task 1.3)。テストで呼び出し順序を `call_order` リストで担保。スモーク AC として、開発機の clean Python で `python -c "from core.accel.probe import probe_cuda; ok, n = probe_cuda(); assert ok and n >= 1"` が exit 0 になることを Sprint 1 受入条件に追加。

### E. 致命的修正 C2 — Phase 1 で whisper postprocess を `whisper_postprocess.py` に抽出

**症状(将来発生する想定)**: Phase 2 で `OpenVINOWhisperTranscriber` 等の Transcriber 実装を追加するとき、各実装が独自に postprocess を書く可能性がある。`core/recording/transcriber.py` に埋まっている幻覚抑制(`_HALLUCINATION_NORM` blocklist)・RMS floor・VAD・`no_speech_prob` フィルタが新実装に取りこぼされると、ライブ字幕の品質が壊れる(幻覚句が表示される、無音区間に空チャンクが出る等)。

**Fix**: Phase 1 Sprint 3 Task 3.1 で `core/recording/whisper_postprocess.py` に **振る舞いを 100% 維持したまま** 抽出する extract refactor を行う。既存 `Transcriber.transcribe_array` はこれらをモジュールから import するだけに変更。Phase 2 で追加される Transcriber 実装は同モジュールを import すれば自動的に幻覚抑制を継承できる。

Phase 1 では `Transcriber` Protocol 化は **行わない**(Phase 2 Sprint 4 に持ち越し)。理由: Protocol 化は実装が 2 つ揃わないと benefit が無く、Phase 1 で行うとリファクタ範囲が広くなる。

### F. AC-CUDA-REGRESSION を **数値ゲート** 化(`tests/perf/baseline.json`)

当初設計の §8.3 の AC-CUDA-REGRESSION は「現状と同等の RTF」と曖昧な目視ゲートだった。Phase 1 では以下の数値ゲートに置き換える:

- Sprint 1 deliverable として、現状 `main`(または `feat/igpu-npu-accel` HEAD 直前)の baseline 数値を `tests/perf/baseline.json` に固定:
  - `cuda_rtf`(30 秒音声の RTF)
  - `cuda_first_chunk_latency_ms`(最初のチャンク到着までの実時間)
  - `cuda_tokens_per_sec`
- `tests/perf/test_cuda_regression.py` を追加。`@pytest.mark.cuda @pytest.mark.slow` でガード。CI ではデフォルト skip、開発機で `pytest -m "cuda and slow"` を Sprint 終わりに手動実行。
- 許容劣化幅は **baseline × 1.10**(10% slack)。これを超えたら fail。
- 以降の全 Sprint で AC-CUDA-REGRESSION は「数値ゲート PASS」を意味する。

### G. テスト隔離用環境変数 `NOTEBOOK_OLLAMA_SKIP_ACCEL_PROBE`

`TestClient(create_app())` が呼ばれる度に `pnputil` を shell-out したり `ctranslate2` を import したりすると、CI が遅くなる・環境差で fail する・並列テストで競合する等の問題が起きる。

**Fix**: `HardwareProbe.run()` は環境変数 `NOTEBOOK_OLLAMA_SKIP_ACCEL_PROBE=1` が立っていたら固定 stub `HwProfile`(`cpu_brand="test-stub"`、全フィールド `None`/`False`/`0`)を返す。`tests/integration/test_api/test_settings_acceleration.py` の `autouse` fixture でこの env を設定する。

### H. 後方互換ガード

Phase 1 で `core.config.AppConfig.audio` に `transcriber_backend` / `diarizer_backend` / `speaker_embed_backend`、`core.config.AppConfig.ollama` に `runtime_backend` / `text_embed_backend` を追加するが、**すべて `"auto"` 既定**。既存ユーザの `settings.json` に新フィールドが無くてもクラッシュしない(`test_existing_settings_json_without_new_fields_still_loads` で担保)。RTX 2080 Ti ユーザの体験は **ゼロ変更**:auto → CUDA path で従来通り動作。

### I. Read-only Settings UI(Phase 1)

Phase 1 の `AccelerationPanel.svelte` は **診断表示のみ**。`<select>` ドロップダウンも `[Apply]` ボタンも存在せず、HW 検出結果と Planner の出力を表示するだけ。NVIDIA ユーザに対しても「今この環境で何が選ばれているか」が即可視化されるため、診断価値が高い。override 操作は Phase 2 Sprint 7 で UI を追加する。

### J. `pyproject.toml` extras の骨格化

Phase 1 では `[project.optional-dependencies]` に `intel = []` / `amd = []` を **空グループ** として追加する。これにより:

- `uv sync --extra intel` が破壊なく走る(何もインストールしない)
- Phase 2 でグループを埋めるとき、構造変更が要らない
- ドキュメントとして将来の依存意図を main に残せる

実パッケージ(`openvino`, `onnxruntime-directml` 等)の追加は Phase 2 Sprint 7。
