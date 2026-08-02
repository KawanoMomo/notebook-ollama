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
  - "[[018-openai-compat-second-contract]]"
  - "[[019-llm-backend-vulkan-promotion]]"
code:
  - apps/api/dependencies.py
  - apps/api/main.py
  - apps/api/schemas/settings.py
  - core/accel/backend_ids.py
  - core/accel/factory.py
  - core/accel/planner.py
  - core/accel/probe.py
  - core/config.py
  - core/ollama/client.py
  - core/ollama/openai_compat.py
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

---

## Update 2026-08-02 — 外部情報の追従とOllama以外のアプローチの検討

2026-06-28 の当初設計・2026-06-29 addendum が依拠した外部情報を 4 系統(Ollama / Intel / AMD / 代替ランタイム)の Web 調査で再検証した。§1〜§12 および addendum A〜J は歴史的記録として保持し、Phase 2 着手時は本 addendum を **正** として扱う。

### K. 前提が崩れた箇所(設計判断に直結)

**K1. Ollama Vulkan は正式リリース済み(§4.3「将来」は誤りに)**

- v0.12.11 で公式バイナリに搭載(`OLLAMA_VULKAN=1` opt-in)、v0.13.0 以降は **バックエンドがあればデフォルト有効**。experimental の但し書きは公式ドキュメントから外れた([docs.ollama.com/gpu](https://docs.ollama.com/gpu)、[Phoronix](https://www.phoronix.com/news/ollama-0.12.11-Vulkan))。
- これにより §4.3 の `ollama-vulkan`(将来)は **現実の選択肢に昇格**。Intel iGPU / AMD iGPU の両方をカバーし、URL 差替すら不要(公式 Ollama のまま)。
- 注意: 弱い iGPU で勝手に有効化され CPU より遅くなる報告あり([#13212](https://github.com/ollama/ollama/issues/13212))。Planner が Vulkan 経路を選ぶ場合も Smoke Test の性能ゲート(R5)は必須。
- 実測目安: Arc 140V iGPU + Qwen3-8B 4bit でデコード約 13.4 tok/s(OpenVINO 経路比 約1.6倍遅、TTFT は Ollama 有利)。
- 一方 **SYCL バックエンドの Ollama 本体入りは断念確定**(PR [#11160](https://github.com/ollama/ollama/pull/11160) が 2026-06-08 未マージクローズ)。Ollama の Intel GPU 路線は Vulkan 一本化。

**K2. IPEX-LLM は採用取り下げ(R1 リスクが顕在化)**

- [intel/ipex-llm](https://github.com/intel/ipex-llm) はアーカイブに加え README に **"known security issues"** が明記された。最終安定版 v2.2.0 は 2025-04 で約1年半更新なし。Portable Zip は入手可能だが **新規採用は不可** と判断する。
- 後継の intel/llm-scaler はデータセンター向け Arc Pro 寄りで、個人向けクライアント GPU の代替になる公式言質なし([llm-scaler#283](https://github.com/intel/llm-scaler/issues/283))。
- **§4.3 の `ipex-llm-ollama` と addendum A の `scripts/install-intel-runtimes.ps1`(Portable Zip 展開)は Phase 2 スコープから削除する。** Intel iGPU の LLM 経路は K4 の代替表に従う。

**K3. 「bge-m3 は OpenVINO 2026.0 で NPU 対応強化」(§4.4)は出典の裏付けなし(訂正)**

- §4.4 で引いた Phoronix / Optimum Intel 2.0 blog のいずれも bge-m3 / BGE 系に言及していない。2026.0 で NPU 対応が明記された埋め込みモデルは **Qwen3-Embedding-0.6B** 等([OpenVINO 2026.0 blog](https://medium.com/openvino-toolkit/openvino-2026-0-new-models-enhanced-genai-and-smarter-compression-bf846a59cda8))。
- `openvino-bge-m3-npu` は「対応実績あり」ではなく **未検証・要 PoC** に格下げ。NPU 埋め込みの常用モデル候補としては Qwen3-Embedding-0.6B を併記する(ただしモデル切替=再インデックスの既知制約に注意)。

**K4. bge-m3 NaN bug の現況(§1・§4.4・R4)**

- [#13572](https://github.com/ollama/ollama/issues/13572) は closed だが、マージされた [PR #13599](https://github.com/ollama/ollama/pull/13599) は NaN/Inf バリデーション追加(エラーの明示化)であり **根本修正ではない**。同症状の継続 issue: [#14657](https://github.com/ollama/ollama/issues/14657)(RTX 2080 Ti=開発機と同型で再現)、[#16625](https://github.com/ollama/ollama/issues/16625)。
- 新たな回避策として **`OLLAMA_FLASH_ATTENTION=false`** が有力(追加バリデーション [PR #14739](https://github.com/ollama/ollama/pull/14739) 作者が根本原因を flash attention 計算と推定)。`num_gpu=0` 一択でなく、GPU を捨てない回避策として検証価値あり(実装時の検証タスクとする)。
- R4 の「`num_gpu=0` を CUDA でも継続」は当面維持。ただし「#13572 が closed だから直った」という誤読を防ぐため本節を参照先とする。

### L. Ollama 以外のアプローチ(新規検討、ユーザ指示による追加)

LLM/Embedding は Ollama HTTP API を共通契約とする方針(§3.2)は維持しつつ、**OpenAI 互換 API も第二の共通契約として認める**。比較結果:

| 候補 | 対応 HW | API | embedding | Windows 導入 | 継続性 |
|---|---|---|---|---|---|
| llama.cpp `llama-server` (Vulkan/SYCL) | Intel/AMD iGPU、NVIDIA | OpenAI 互換 (`/v1/chat/completions`, `/v1/embeddings`, `/v1/rerank`) | bge-m3 GGUF の dense が可 | プリビルド zip(pip 不要) | ggml-org 本体、ほぼ毎日リリース |
| llama.cpp OpenVINO backend | Intel CPU/GPU/**NPU** | 同上 | **限定的と明記** | 自前ビルドのみ | 2026-04 upstream、experimental |
| OpenVINO Model Server (OVMS) | Intel CPU/GPU/**NPU** | OpenAI 互換 + embeddings + rerank | あり(要 OpenVINO IR 変換、bge-m3 の名指し実績なし) | ネイティブバイナリ / Docker、2025.4 でサービス化 | Intel 公式、四半期リリース |
| Microsoft Foundry Local | HW 自動検出(OpenVINO/QNN/DirectML/Vitis AI EP) | OpenAI 互換 | v1.1 で正式対応(カタログの ONNX モデルのみ) | `winget install`、**Win11 24H2 以降** | MS 公式 GA。Intel/AMD NPU の実利用可否は記述に揺れ |
| AMD Lemonade Server | Ryzen AI 300 NPU + Radeon iGPU の **hybrid 実行** | OpenAI 互換 (:13305) | llamacpp/flm recipe のみ。**NPU(OGA)経路は非対応**、ユーザ pull モデルで 501 の既知不具合([#1745](https://github.com/lemonade-sdk/lemonade/issues/1745)) | .msi / pip、Apache 2.0 | AMD スポンサーのコミュニティ主導(公式製品ではない)。成熟途上 |
| LM Studio (`llmster` headless) | Vulkan/CUDA/ROCm | OpenAI 互換 (:1234) | あり(GGUF 直) | インストーラ、2025-07 から商用も無償 | GUI 中心思想、常時稼働は不向きの評 |
| Nexa SDK | Qualcomm/Intel/AMD の **3社 NPU** | OpenAI 互換 | 確証なし | CLI/pip/Docker | 独自路線、要 PoC |

**推薦(Phase 2 の LLM バックエンド構成)**:

- **Intel iGPU**: 第一候補 `llama-server`(Vulkan または SYCL ビルド)。GGUF 資産をそのまま使え、chat + embeddings を単一プロセスの OpenAI 互換で賄える。第二候補は公式 Ollama + Vulkan(URL 差替すら不要で最小変更)。
- **Intel NPU**: `llama-server` の OpenVINO backend は embedding 非対応・自前ビルドのため見送り。NPU を使うなら **OVMS**(生成=NPU、埋め込み=GPU/CPU の `embeddings_ov`)。代償は OpenVINO IR 変換工程。
- **AMD Ryzen AI**: 第一候補 **Lemonade Server**(NPU+iGPU hybrid を OpenAI 互換の裏に隠蔽する唯一の選択肢)。embedding は llamacpp recipe(GGUF)に分離。不確実性を嫌うなら公式 Ollama + Vulkan が最小リスク。
- **AMD iGPU のみ**: 公式 Ollama + Vulkan(780M/890M は ROCm でなく Vulkan が現実解。ROCm は Windows APU 非対応)。

**アーキテクチャへの影響**: `_ClientLike` Protocol(§4.3)に加えて **OpenAI 互換クライアント(`OpenAICompatClient`)を Phase 2 の第一級実装とする**。これにより上表のどのランタイムにも URL + モデル名の設定だけで接続できる。`OVGenAIClient`(OpenVINO GenAI 直叩き)は OVMS がある限り優先度を下げる。

### M. 横断的設計指針: 生成と embedding の非対称構成(最重要)

今回の調査範囲で、**NPU 経路で embedding まで完走できるランタイムは実質存在しない**(Lemonade は明確に非対応、llama.cpp OpenVINO は「限定的」、OVMS も NPU embedding の確証なし)。したがって:

- `BackendPlan` の `llm` と `text_embed` は **独立したエンドポイント設定**とする(現行設計は既にフィールド分離済みなので構造変更不要。「同一 Ollama を共有する」暗黙前提だけを捨てる)。
- デフォルト構成は「**生成 = NPU/iGPU、埋め込み = iGPU/CPU**」の非対称。どのベンダーに転んでも設計変更が不要になる。

### N. バージョン・HW 表の追従

**Intel**(出典: [OpenVINO releases](https://github.com/openvinotoolkit/openvino/releases)、[optimum-intel PyPI](https://pypi.org/project/optimum-intel/)):

- OpenVINO 最新は **2026.2.1**。2026.2 系の破壊的変更に注意: `openvino.runtime` ネームスペース削除、CPU プラグイン AVX2 必須、NNCF `create_compressed_model()` 削除。
- 依存指定は `optimum[openvino]>=2.0`(§9)ではなく **`optimum-intel>=2.0`** に変更(extras は非推奨化、OpenVINO/NNCF は同梱)。`OVModelForSpeechSeq2Seq` / `OVModelForFeatureExtraction` のクラス名は現行も有効。
- **NPU の static shape 制約は緩和方向**: NPU Driver 1.35.0 が dynamic shape 最適化を追加、GenAI の `STATIC_PIPELINE` は必須からトラブルシュート用に後退。§4.1 の「distil-whisper-large-v2 固定」は Phase 2 着手時に large-v3 / large-v3-turbo を再評価する(R2 のリスク度を下げる)。※一次ドキュメント(docs.openvino.ai の NPU GenAI ページ)は実装前に人手確認のこと。
- `onnxruntime-openvino` 1.24.1 がバンドルする OpenVINO は 2025.4.1 系で、**openvino 2026.x との同一 venv 版ズレに注意**(EP 互換範囲は直近3リリース。要実機検証)。DirectML は **maintenance mode**(新機能開発は Windows ML へ移行)— sherpa-onnx の DML 経路は descope 済(addendum C)だが、将来再検討する場合は Windows ML を先に評価する。
- HW 表に追加: **Panther Lake / Core Ultra series 3**(Arc Xe3 / NPU 5 / 最大50 TOPS、OpenVINO 2026.1 で公式サポート)、**Wildcat Lake**(廉価帯、NPU 15-17 TOPS)。検出方式 `Core().available_devices` は世代非依存のため Probe のロジック変更は不要。

**AMD**(出典: [Ryzen AI relnotes](https://ryzenai.docs.amd.com/en/latest/relnotes.html)、[Phoronix](https://www.phoronix.com/news/Ryzen-AI-Software-1.8)):

- Ryzen AI Software 最新は **1.8.0**(2026-07-23)。OS 要件(Win11 build 22621.3527 以上)は不変。NPU ドライバ要件 32.0.203.280 以降(production は 32.0.203.376)。
- whisper.cpp fork の「encoder=NPU / decoder=CPU」構成は不変、1.8.0 で **large-v3-turbo が公式言及**・短尺音声の RTF 改善。ただし `amd-whispercpp-npu` の v1 削除判断(addendum B)は維持(継続性リスクは不変)。
- HW 表に追加: **Gorgon Point = Ryzen AI 400 シリーズ**(XDNA 2、最大 55-60 TOPS)。ただし **RAI 1.8.0 の対応リスト未収載**のため「HW としては存在、公式ソフトサポート未反映」と書き分ける。NPU の PCI ID は公開資料で未確認(実機確認タスク)。
- Medusa Point(Zen 6 + XDNA 3、2027 予定)はロードマップ注記に留める。

**共通**:

- CTranslate2 最新は **4.8.1**(CUDA 12.8 / cuDNN 9 / Python 3.13 対応、**cuDNN 8 と Python 3.8 廃止**)。C1 fix の `_register_cuda_dll_dirs()` が探す DLL 名(`cudnn_ops_infer64_8.dll` = cuDNN 8 系)は CTranslate2 更新時に変わるため、アップグレード時は DLL 名の追従を確認する。
- faster-whisper 最新は 1.2.1(large-v3-turbo / distil-large-v3.5 対応済)。CUDA 以外のバックエンド追加はなし — 「AMD では faster-whisper は加速できない」という §4.1 の構図は不変。

### O. Phase 2 バックエンド表(改訂版)

§4.3 / §4.4 の表を以下に置き換える(STT §4.1 は distil モデル再評価以外は不変、sherpa-onnx は CPU 固定のまま):

**LLM**:

| バックエンド ID | 経路 | 対象 HW | 状態 |
|---|---|---|---|
| `ollama-cuda`(現状) | 公式 Ollama | NVIDIA dGPU | 実装済(Phase 1) |
| `ollama-vulkan` | 公式 Ollama(Vulkan デフォルト有効) | Intel iGPU / AMD iGPU | **昇格**: URL 差替不要、Phase 2 最小コスト経路 |
| `openai-compat` | `llama-server` / OVMS / Lemonade / LM Studio 等 | 各表参照 | **新設**: `OpenAICompatClient` + endpoint URL + モデル名 |
| ~~`ipex-llm-ollama`~~ | ~~IPEX-LLM Portable Zip~~ | — | **削除**(K2: セキュリティ問題) |
| `openvino-genai-server` | `OVGenAIClient` 直叩き | Intel NPU | 優先度低下(OVMS を `openai-compat` で使う方が薄い) |

**Text Embedding**:

| バックエンド ID | 経路 | 対象 HW | 状態 |
|---|---|---|---|
| `ollama-bge-m3-cpu`(現状) | Ollama + `num_gpu=0` | 全環境 | 実装済。`OLLAMA_FLASH_ATTENTION=false` の GPU 経路検証タスクを追加(K4) |
| `openai-compat-embed` | `llama-server /v1/embeddings`(bge-m3 GGUF)等 | Intel/AMD iGPU | **新設** |
| `openvino-bge-m3-igpu` | Optimum Intel 直叩き | Intel iGPU | 維持(要 PoC) |
| `openvino-bge-m3-npu` | 同上 device=NPU | Intel NPU | **格下げ**: 未検証・要 PoC(K3)。代替候補 Qwen3-Embedding-0.6B(再インデックス必要) |

### P. Phase 2 着手時の追加検証タスク

1. `OLLAMA_FLASH_ATTENTION=false` で bge-m3 GPU 経路の NaN 再現有無を確認(開発機 RTX 2080 Ti で可能。Phase 2 を待たず実施可。ただし Ollama サーバーの再起動が必要なため、開発機の Ollama を占有できるタイミングで実施する)
2. docs.openvino.ai の NPU GenAI ページを人手確認(static shape 制約の現行仕様確定)
3. `onnxruntime-openvino` と `openvino` 2026.x の同一 venv 共存確認
4. Gorgon Point NPU の PCI ID 実機確認(Probe の AMD 判定表更新)
5. CTranslate2 4.8.x 更新時の cuDNN 9 系 DLL 名追従(C1 fix の回帰確認)

### Q. Phase 1.5 実装記録(2026-08-02)

本 addendum のうち、開発機(NVIDIA のみ)で実装・自動テスト可能な範囲を **Phase 1.5** としてコードに反映した。BE 全テスト 1490 件 PASS(新規 41 件)。既存 NVIDIA ユーザー(全設定 "auto")の挙動はゼロ変更。

**実装内容**:

| 項目 | 反映先 |
|---|---|
| K1: `ollama-vulkan` 昇格(Intel/AMD iGPU の auto 選択先、builder は `ollama-cuda` と共通) | `core/accel/backend_ids.py` / `planner.py` / `plan.py` / `factory.py` |
| K2: `ipex-llm-ollama` 削除 + `ollama-directml` 削除(Ollama に DML バックエンドは存在しない)。再導入ガード(import 時 sentinel) | `backend_ids.py` `_DROPPED_LLM_IDS` |
| L: `OpenAICompatClient` 新設(`_ClientLike` 準拠、SSE / ThinkingChunk / done_reason / Ollama vision 形式→content-parts 変換 / AppError 同コード正規化) | `core/ollama/openai_compat.py`(新規) |
| L: `openai-compat` / `openai-compat-embed` バックエンド(**auto 選択なし、user override のみ**) | `planner.py` / `factory.py` / `core/config.py` |
| M: 生成と embedding の独立エンドポイント(`openai_compat_embed_endpoint`、空なら `openai_compat_endpoint` に fallback) | `core/config.py` / `factory.py` |
| override 適用: `BackendPlanner.plan(hw, BackendOverrides)`(§5.1 step 5 の実装。degrade 経路でも override 保持) | `planner.py` / `apps/api/dependencies.py` |
| STT id `amd-whispercpp-dml` → `amd-whispercpp-vulkan` 改名(whisper.cpp に DML バックエンドは無い。Phase 2 未実装 ID のままの改名) | `backend_ids.py` / `planner.py` |
| 設定 API: `runtime_backend` / `text_embed_backend` の Literal 拡張、`openai_compat_*` フィールド追加(GET 応答に api_key は含めない) | `core/config.py` / `apps/api/schemas/settings.py` / `routers/settings.py` |

**設計判断(Phase 1.5 固有)**:

- `openai-compat` 指定で endpoint 未設定の場合は **起動時に ValueError で明示停止**(remediation 付きメッセージ)。§6.1「LLM は黙って切替えない」に従い、静かなフォールバックはしない。設定手段が settings.json 手編集のみである現状と対称。
- `openai-compat-embed` は LLM 側 gateway を再利用せず**専用 gateway を建てる**(経路が異なるため)。`embedding_options`(`num_gpu=0`)は Ollama 固有の NaN 回避であり OpenAI 経路には渡さない。
- Ollama options → OpenAI パラメータは最小マッピング(`num_predict`→`max_tokens`、`temperature`、`top_p`)。対応概念の無い option は dev ログに警告して破棄。

**Phase 1.5 で実装していないもの**: override 操作 UI(Phase 2 Sprint 7)、OpenAI 互換サーバーの導入スクリプト、P 節の検証タスク(P1 は Ollama 再起動を要するため保留)、`openvino-*` / `amd-whispercpp-vulkan` の実 builder(Phase 2、実機待ち)。

**コードレビュー反映(2026-08-02、/code-review 9件)**:

- 埋め込み経路の配線を修正: 取込(`IngestionPipeline`)と検索(`RetrievalService`)の埋め込みは `text_embedder.gateway` を使うようにし、`text_embed_backend` の選択が実際の呼び出しまで通るようにした(従来は LLM 側 gateway に固定で、`openai-compat-embed` が死んでいた / `runtime_backend=openai-compat` 時に埋め込みまで compat サーバーへ誤ルーティングされた)
- Factory: LLM が openai-compat のとき `ollama-bge-m3-cpu` embedder が LLM 側 gateway を再利用しないようガード(embed は必ず Ollama へ)
- チャット事前検査(`_resolve_num_ctx`)は openai-compat 時に Ollama `/api/show` を叩かず num_ctx=8192 で予算検査のみ(compat 運用でチャットが塞がるのを解消)
- `PUT /api/settings/ollama` と再インデックス保存が ollama セクションを固定キーで再構築して手編集フィールド(`runtime_backend` / `openai_compat_*` 等)を消すバグを、既存キーへのマージ更新に修正
- Planner: NPU contention 判定を STT override 適用後の最終 STT id で行うよう修正
- vision capability probe を best-effort 化(取得失敗はチャットを巻き込まず vision なし扱い)
- ADR ドラフト 2 件を起票(2026-08-02 に承認・採番済み: [[018-openai-compat-second-contract|ADR-018]] / [[019-llm-backend-vulkan-promotion|ADR-019]])

**既知制限(Phase 1.5、openai-compat 運用時)**:

1. **モデルメタ層は Ollama 前提のまま**: 設定 UI のモデル検証・モデル一覧・vision capability・num_ctx 取得は Ollama に問い合わせる。openai-compat のモデル名は settings.json 手編集でのみ設定可能で、num_ctx は既定 8192 と見なす(打ち切りは done_reason=length の自動継続で救済)
2. **録音パイプラインは Ollama 前提のまま**: LLM 補助タスク(話者名推定・校正・タイトル)と埋め込みが同一 dep を共有しており、Phase 1.5 では分離しない。runtime_backend=openai-compat で録音取込した場合、録音の埋め込みも compat サーバーに向かう(recording extra 利用者は Ollama 併用を推奨)
3. **MCP サーバーの ask 経路**も Ollama 直結のまま(将来課題)
