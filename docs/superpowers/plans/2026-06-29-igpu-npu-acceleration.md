# Intel iGPU/NPU・AMD Ryzen AI 対応 Implementation Plan (Phase 1)

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development`(推奨)または `superpowers:executing-plans` でタスクごとに実装する。各 Step はチェックボックス(`- [ ]`)で進捗管理する。

> **Status (2026-07-02): Phase 1 (Sprint 1〜3) 実装完了・検証済み。** 本文中の `- [ ]` は各 Step 実施時にチェックが更新されなかった記録漏れで、実装未了を意味しない(git log で Sprint 1/2/3 各コミット確認済み)。完了の裏付け: `tests/unit/accel/` 相当 60 件 PASS、CUDA 回帰ゲート (`pytest -m "cuda and slow"`) 3件 PASS、Sprint3 最終 smoke report PASS (`docs/eval/2026-06-30-igpu-npu-accel-sprint3-final/`)。2026-07-02 に origin/master (17コミット先行) とのコンフリクトを解消・マージし、マージ後の実機視覚検証も PASS (`docs/eval/2026-07-02-igpu-npu-accel-post-merge/`)。Phase 2 (Intel/AMD 実バックエンド) は開発機に対象ハードウェアが無いため計画上無期限延期のまま(下記 Phase 2 セクション参照)。

## 本プランのスコープ — Phase 1 限定

**本 PR は Phase 1(Sprint 1〜3)のみを実装する。** Sprint 4〜7(Intel/AMD 実バックエンド・UI 上書き・インストールスクリプト)は **Phase 2 として後送り** とし、本書末尾の `## Phase 2 (deferred)` セクションに移動する。

Phase 1 で得る価値:

1. **HardwareProbe / BackendPlanner / BackendFactory の DI 骨格**: 既存 CUDA 経路を Plan 経由に置き換えるが、**動作回帰ゼロ** が AC。
2. **CUDA リグレッション数値ハーネス**: 現在の `main` ブランチの RTF / tok/s / first-chunk latency を `tests/perf/baseline.json` に固定し、以降の改修で 10% 以内の劣化までしか許容しない自動ゲート。
3. **Read-only Acceleration タブ**: NVIDIA ユーザに検出 HW と選択 Plan の **診断情報** を即提供する(override 操作は Phase 2)。
4. **whisper postprocess の抽出リファクタ**: 将来 Phase 2 で Transcriber 実装が増えたとき、幻覚抑制ロジックを各実装に取りこぼさない土台を作る(C2 fix)。

Phase 1 で実装 **しない** もの(Phase 2 deferred、本書末尾参照):

- Intel iGPU/NPU 用の Whisper / bge-m3 / Ollama ランタイム実装
- AMD Ryzen AI 用の Whisper 実装(`amd-whispercpp-npu` は **v1 から完全に削除**、本書のどこにも残らない)
- sherpa-onnx の GPU/NPU provider 切替(Diarizer + SpeakerEmbedder は **Phase 1/2 とも CPU 固定**、既知制約)
- ユーザ override UI の `<select>` + `[Apply]` 操作
- IPEX-LLM Ollama Portable Zip の子プロセス起動
- インストールスクリプト(`scripts/install-intel-runtimes.ps1` 等)

**Goal (Phase 1):** 既存 NVIDIA CUDA 経路の動作を 1 ミリも変えずに、`HardwareProbe → BackendPlanner → BackendFactory` の 3 段パイプラインを既存コアに差し込み、CUDA + CPU 経路だけを Plan 経由で組み立てる。Phase 2 で実バックエンドを足すときに既存配線を触らなくて済む状態を作る。

**Architecture:** バックエンドは FastAPI(`apps/api/`)+ 純ドメイン `core/`。新規モジュール `core/accel/` に probe/planner/factory/plan を集約し、既存の `core/recording/transcriber.py`・`core/recording/diarizer.py`・`core/recording/embeddings.py`・`core/ollama/gateway.py` は **Phase 1 では Factory builder から間接生成されるようになるだけ**で内部実装は触らない(例外: `core/recording/whisper_postprocess.py` への extract refactor。C2 fix)。Planner 出力 `BackendPlan` は 5 フィールドを持つが、Phase 1 で実 builder が登録されるのは CUDA + CPU 系のみ(`faster-whisper-cuda`, `faster-whisper-cpu`, `sherpa-onnx-cpu`, `ollama-cuda`, `ollama-bge-m3-cpu`)。

**Tech Stack:** Python (FastAPI, pydantic, structlog) / SvelteKit + TypeScript / pytest / Playwright MCP。Phase 1 では新規ランタイム依存は **一切追加しない**(`pyproject.toml` の `[project.optional-dependencies]` に `intel` / `amd` の **空グループ** を骨格として置くのみ。Phase 2 で中身を入れる)。

## Global Constraints

- ブランチは `feat/igpu-npu-accel`(現在のブランチ)で作業。master 直接編集禁止。
- コミットメッセージに Co-Authored-By trailer を付けない(ユーザ規約)。
- **CUDA 経路の動作回帰なし** が AC-CUDA-REGRESSION として全 Sprint 共通の最終ゲート。Phase 1 では `tests/perf/test_cuda_regression.py` が `pytest -m "cuda and slow"` で自動実行され、baseline RTF × 1.10 を超えたら fail。
- 新規 import を `try/except ImportError` でガードし、extras 未インストール環境(=Phase 1 の全環境)でも Planner と Probe が正常起動する。
- 既存テストを壊さない。新規 Protocol 実装はユニット(モック)で完結。
- テスト規約: `pyproject.toml` で `asyncio_mode = "auto"` 済。async テストの `@pytest.mark.asyncio` は省略可。
- `@pytest.mark.runtime` / `@pytest.mark.cuda` / `@pytest.mark.slow` を Sprint 1 で `pyproject.toml` に登録。CI ではデフォルト skip、開発機で `pytest -m "cuda and slow"` を手動実行。
- **GUI 変更は自動テスト GREEN だけで PASS にしない**(ユーザ規約)。Sprint 3 の read-only Acceleration タブは Playwright MCP の実機スクリーンショットを必須とする。
- `npm run build` 後に `apps/web/dist/.gitkeep` が消える既知問題があるため、フロント commit 前に `git checkout -- apps/web/dist/.gitkeep` を行う。
- **Planner にハード依存を持たせない**(probe を別モジュールに分離する重要動機、spec §8.1)。Planner はモック `HwProfile` だけでテストできる純関数として保つ。
- 設定ファイル(`settings.json`)スキーマ変更は **後方互換のみ**。`audio.transcriber_backend` 等は `"auto"` 既定とし、既存ユーザの `settings.json` を読んでクラッシュさせない(`test_existing_settings_json_without_new_fields_still_loads` で担保)。
- **環境変数 `NOTEBOOK_OLLAMA_SKIP_ACCEL_PROBE=1`** が立っている場合、`HardwareProbe.run()` は固定のダミー `HwProfile`(CPU only / no GPU)を返してショートサーキットする。テスト隔離用(`TestClient(create_app())` の度に pnputil を shell-out しない)。
- **CUDA probe の DLL search path 注入(C1 fix)**: `probe_cuda()` は `import ctranslate2` の前に必ず `_register_cuda_dll_dirs()`(または同等の `os.add_dll_directory` 呼び出し)を実行する。これを怠ると、`uv` 経由で起動した開発機の clean Python から CUDA が見えず Planner が黙って CPU を選ぶ。Sprint 1 のスモーク AC として、開発機の clean Python で `probe_cuda()` を呼び `(True, ≥1)` が返ることをアサート。

## テスト戦略(開発機ハードウェア前提)

**開発機**: Windows 11 + Intel i9-12900KF + NVIDIA RTX 2080 Ti(spec §2 で「現状資産」と分類されている dGPU のみ)。**Intel iGPU/NPU と AMD Ryzen AI ハードウェアは開発機に存在せず、調達予定もない。** したがって本 Phase では Intel/AMD 実機検証は不可能であり、Phase 2 は事実上 **無期限延期** となる(ユーザ決定 2)。

Phase 1 の CI / ローカルテストは以下に集中する:

1. **モック probe 単体テスト**: `openvino.Core` / `pnputil` / `DXCore` / `ctranslate2.get_cuda_device_count` を全部モックし、spec §2 の全 HW プロファイル(Intel MTL/LNL/ARL + AMD PHX/HPT/STX/STX-Halo/KRK + NVIDIA + 何もなし)を再現する parametrize テスト。**Planner ロジックは Phase 2 で必要になる Intel/AMD 分岐も実装しテストする**(純関数ゆえハード非依存。Phase 2 着手時に Planner を再触らずに済む)。
2. **Planner 表駆動テスト**: `HwProfile + UserOverride → BackendPlan` の全組合せ。Phase 1 では Factory が CUDA + CPU 系 builder しか持たないため、開発機の `HwProfile` を渡すと `stt=faster-whisper-cuda` が選ばれ Factory がそれを build できる(=既存挙動と一致)。
3. **Factory 単体テスト**: Phase 1 builder(CUDA/CPU 系)が plan に従って正しく呼ばれることをモックで検証。Phase 2 ID(`openvino-whisper-igpu` 等)を渡すと **「Phase 2 not yet implemented」と明示エラー**(silent fail 防止)。
4. **CUDA 数値リグレッション**: `tests/perf/baseline.json` に固定した baseline と毎回比較。10% 以上の悪化で fail(`pytest -m "cuda and slow"`)。
5. **whisper postprocess 単体テスト**: extract refactor 後の `core/recording/whisper_postprocess.py` の関数(`apply_rms_floor`, `is_voice`, `should_filter_hallucination`)が、リファクタ前の `core/recording/transcriber.py` 内挙動と完全一致することをユニットで担保。

**Phase 1 では Intel/AMD 実機検証は完全に対象外** とし、`docs/testing/igpu-npu-acceptance.md` には「Phase 2 に着手するときの参考」として spec §8.2 の表を雛形だけ置く(各セルは `Phase 2 未着手` ステータス)。

## Sprint 依存関係

```
Sprint 1 (Probe + Baseline 数値ハーネス)
   ↓
Sprint 2 (Planner — Phase 2 用 ID 群も含む。amd-whispercpp-npu は permanent 削除、sherpa-onnx は cpu 固定)
   ↓
Sprint 3 (whisper_postprocess extract + Settings + Factory skeleton + DI + read-only Acceleration タブ + CUDA 回帰ゲート)
```

Phase 2(後送り)の Sprint 4〜7 は本書末尾の deferred セクション参照。

---

## Sprint 1: HardwareProbe + HwProfile + extras 骨格 + CUDA Baseline 数値ハーネス

spec §2 (ターゲットハードウェア)・§3.1(HardwareProbe ブロック)・§9(依存と extras)に対応する基礎。実機 iGPU/NPU 無しでも全 HW プロファイルをモックで再現できるよう、probe を 4 つの独立した小プローブに分割する。本 Sprint では **CUDA baseline 数値ハーネス(`tests/perf/baseline.json` + `tests/perf/test_cuda_regression.py`)も同時に作る**。これは以降の全 Sprint で AC-CUDA-REGRESSION を「目視」ではなく「数値ゲート」で守るため。

**Files:**
- Add: `core/accel/__init__.py`
- Add: `core/accel/probe.py`(`HwProfile` dataclass + `HardwareProbe` + 4 つのプローブ関数 + `_register_cuda_dll_dirs` + `NOTEBOOK_OLLAMA_SKIP_ACCEL_PROBE` 対応)
- Add: `core/accel/vendors.py`(`Vendor` Enum と AMD PCI ID テーブル)
- Add: `tests/unit/accel/__init__.py`
- Add: `tests/unit/accel/test_probe.py`(モック probe parametrize)
- Add: `tests/unit/accel/test_vendors.py`
- Add: `tests/perf/__init__.py`
- Add: `tests/perf/baseline.json`(現状 main 計測値: `cuda_rtf`, `cuda_first_chunk_latency_ms`, `cuda_tokens_per_sec`)
- Add: `tests/perf/test_cuda_regression.py`(`@pytest.mark.cuda @pytest.mark.slow`)
- Add: `docs/testing/igpu-npu-acceptance.md`(Phase 2 用雛形のみ)
- Modify: `pyproject.toml`(`intel` / `amd` extras を **空グループで** 追加、`runtime` / `cuda` / `slow` / `intel_igpu` / `intel_npu` マーカー追加)

**Interfaces:**
- Consumes: 既存 `core.config.AppConfig`(参照のみ、変更なし)。
- Produces(Sprint 2 以降が依存):
  - `core.accel.probe.HwProfile`(frozen dataclass):
    ```python
    @dataclass(frozen=True)
    class HwProfile:
        cpu_brand: str
        dgpu: str | None
        igpu: str | None
        npu: str | None
        vram_mb: int | None
        ryzen_ai_gen: int | None
        openvino_devices: tuple[str, ...]
        has_directml: bool
        has_cuda: bool
        cuda_device_count: int
    ```
  - `core.accel.probe.HardwareProbe.run() -> HwProfile`(同期。`NOTEBOOK_OLLAMA_SKIP_ACCEL_PROBE=1` でショートサーキット)
  - サブプローブ(個別にモック可能):
    - `probe_openvino() -> tuple[str, ...]`
    - `probe_amd_npu() -> tuple[str | None, int | None]`
    - `probe_dxcore() -> bool`
    - `probe_cuda() -> tuple[bool, int]` — **`_register_cuda_dll_dirs()` 呼び出し済み**(C1 fix)
  - `core.accel.vendors.Vendor`(Enum)
  - `core.accel.vendors.AMD_NPU_PCI_IDS: dict[str, int]`
- 数値ベースライン: `tests/perf/baseline.json`(将来 Sprint で読み込まれる固定 baseline)

### Task 1.1: `pyproject.toml` に **空の** extras と marker を追加

ユーザ決定: Phase 1 では `intel` / `amd` extras は中身を入れない(`uv sync --extra intel` が成功するが何もインストールしない)。これにより Phase 2 で extras を埋めるときの構造を先に固めておく。

- [ ] **Step 1 (RED): 既存テストが壊れないことを baseline 確認**
  Run: `uv run pytest tests/ -x --co -q | tail -5`
  Expected: テスト collection が問題なく完了。

- [ ] **Step 2 (GREEN): `pyproject.toml` を編集**
  `[project.optional-dependencies]` ブロックに以下を追加(空グループ):
  ```toml
  intel = [
      # Phase 2: openvino, optimum[openvino], onnxruntime-openvino, onnxruntime-directml
      # Phase 1 は空(構造のみ documents future intent)。
  ]
  amd = [
      # Phase 2: onnxruntime-directml (DirectML 経路のみ。AMD NPU 用 whisper.cpp は v1 から除外)
      # Phase 1 は空。
  ]
  ```
  `[tool.pytest.ini_options]` の `markers` ブロックに追加:
  ```toml
      "runtime: tests that require real GPU/NPU hardware (skipped in CI; run locally with -m runtime)",
      "cuda: tests that require an NVIDIA CUDA device",
      "slow: tests that exercise real model inference (>5s wall clock)",
      "intel_igpu: tests that require an Intel Arc/Xe-LPG/Xe2 iGPU (Phase 2)",
      "intel_npu: tests that require an Intel NPU 3/4 (Phase 2)",
  ```
  **注**: `amd_npu` マーカーは追加しない(v1 から `amd-whispercpp-npu` を削除したため、AMD NPU 実機検証は Phase 2 でも対象外)。

- [ ] **Step 3 (REFACTOR): `uv sync --extra intel` が解析エラーなく完了することを確認**
  Run: `uv sync --extra intel 2>&1 | tail -5`
  Expected: 空グループなので追加インストールなし、エラーなし。

- [ ] **Step 4: コミット**
  ```
  git add pyproject.toml
  git commit -m "build: add empty intel/amd extras and runtime/cuda/slow markers (Phase 1)"
  ```

### Task 1.2: `Vendor` Enum + AMD PCI ID テーブル

- [ ] **Step 1 (RED): `tests/unit/accel/test_vendors.py` を作成**
  ```python
  from core.accel.vendors import AMD_NPU_PCI_IDS, Vendor

  def test_amd_phoenix_xdna1_ven_1022_dev_1502():
      assert AMD_NPU_PCI_IDS["VEN_1022&DEV_1502"] == 1  # XDNA1

  def test_amd_strix_xdna2_rev_00_10_11():
      for rev in ("00", "10", "11"):
          assert AMD_NPU_PCI_IDS[f"VEN_1022&DEV_17F0&REV_{rev}"] == 2

  def test_amd_krackan_point_rev_20_xdna2():
      assert AMD_NPU_PCI_IDS["VEN_1022&DEV_17F0&REV_20"] == 2

  def test_vendor_enum_values():
      assert Vendor.INTEL.value == "intel"
      assert Vendor.AMD.value == "amd"
      assert Vendor.NVIDIA.value == "nvidia"
      assert Vendor.UNKNOWN.value == "unknown"
  ```

- [ ] **Step 2 (GREEN): `core/accel/__init__.py` を空ファイル、`core/accel/vendors.py` を作成**
  ```python
  from __future__ import annotations
  from enum import Enum


  class Vendor(str, Enum):
      INTEL = "intel"
      AMD = "amd"
      NVIDIA = "nvidia"
      UNKNOWN = "unknown"


  AMD_NPU_PCI_IDS: dict[str, int] = {
      "VEN_1022&DEV_1502": 1,
      "VEN_1022&DEV_17F0&REV_00": 2,
      "VEN_1022&DEV_17F0&REV_10": 2,
      "VEN_1022&DEV_17F0&REV_11": 2,
      "VEN_1022&DEV_17F0&REV_20": 2,
  }
  ```

- [ ] **Step 3: 緑確認 + コミット**
  ```
  uv run pytest tests/unit/accel/test_vendors.py -v
  git add core/accel/__init__.py core/accel/vendors.py tests/unit/accel/__init__.py tests/unit/accel/test_vendors.py
  git commit -m "feat(accel): add Vendor enum and AMD NPU PCI id table"
  ```

### Task 1.3: 4 サブプローブを実装(C1 fix: probe_cuda は DLL search path を先に登録)

**C1 (critical fix)**: `_register_cuda_dll_dirs()` を `import ctranslate2` の前に呼ばないと、`uv` 経由で起動した clean Python から `cudnn_ops_infer64_8.dll` が見つからず `ctranslate2.get_cuda_device_count()` が 0 を返す → Planner が CPU を黙って選び、ユーザは「なぜか CUDA が効かない」状態に陥る。既存の `core/recording/transcriber.py` には同等の `_register_cuda_dll_dirs()` ヘルパが存在するため、Sprint 1 では同モジュールから import して使う(コード重複は Sprint 3 で `core/accel/probe.py` 側に同等品を切り出すか方針決定)。

- [ ] **Step 1 (RED): `tests/unit/accel/test_probe.py` を作成**
  ```python
  from unittest.mock import MagicMock, patch
  import pytest

  from core.accel.probe import (
      probe_amd_npu, probe_cuda, probe_dxcore, probe_openvino,
  )


  def test_probe_openvino_returns_devices_when_module_present():
      fake_core = MagicMock()
      fake_core.return_value.available_devices = ["CPU", "GPU", "NPU"]
      fake_mod = MagicMock(Core=fake_core)
      with patch.dict("sys.modules", {"openvino": fake_mod}):
          assert probe_openvino() == ("CPU", "GPU", "NPU")

  def test_probe_openvino_returns_empty_when_module_missing():
      with patch.dict("sys.modules", {"openvino": None}):
          assert probe_openvino() == ()

  def test_probe_amd_npu_detects_phoenix_xdna1():
      fake_output = "Device ID: PCI\\VEN_1022&DEV_1502&SUBSYS_00000000&REV_00\\X\n"
      with patch("core.accel.probe._run_pnputil", return_value=fake_output):
          name, gen = probe_amd_npu()
      assert name == "AMD XDNA 1"
      assert gen == 1

  def test_probe_amd_npu_detects_strix_xdna2():
      fake_output = "Device ID: PCI\\VEN_1022&DEV_17F0&SUBSYS_X&REV_10\\Y\n"
      with patch("core.accel.probe._run_pnputil", return_value=fake_output):
          name, gen = probe_amd_npu()
      assert name == "AMD XDNA 2"
      assert gen == 2

  def test_probe_amd_npu_returns_none_when_no_match():
      with patch("core.accel.probe._run_pnputil", return_value=""):
          assert probe_amd_npu() == (None, None)

  def test_probe_cuda_returns_zero_when_module_missing():
      with patch.dict("sys.modules", {"ctranslate2": None}):
          has, n = probe_cuda()
      assert (has, n) == (False, 0)

  def test_probe_cuda_calls_register_dll_dirs_before_import():
      """C1 fix: DLL search path 登録は必ず import ctranslate2 の前。"""
      call_order: list[str] = []
      def fake_register():
          call_order.append("register")
      fake_ct2 = MagicMock(get_cuda_device_count=MagicMock(side_effect=lambda: (call_order.append("import"), 1)[1]))
      with (
          patch("core.accel.probe._register_cuda_dll_dirs", side_effect=fake_register),
          patch.dict("sys.modules", {"ctranslate2": fake_ct2}),
      ):
          probe_cuda()
      assert call_order[0] == "register", f"expected register-before-import, got {call_order}"

  def test_probe_dxcore_false_when_unavailable():
      with patch("sys.platform", "linux"):
          assert probe_dxcore() is False
  ```

- [ ] **Step 2 (GREEN): `core/accel/probe.py` を実装**
  ```python
  from __future__ import annotations

  import os
  import re
  import subprocess
  import sys
  from dataclasses import dataclass

  from core.accel.vendors import AMD_NPU_PCI_IDS

  _AMD_RE = re.compile(
      r"VEN_1022&DEV_(?P<dev>[0-9A-F]{4})(?:[^\\]*REV_(?P<rev>[0-9A-F]{2}))?",
      re.IGNORECASE,
  )


  @dataclass(frozen=True)
  class HwProfile:
      cpu_brand: str
      dgpu: str | None
      igpu: str | None
      npu: str | None
      vram_mb: int | None
      ryzen_ai_gen: int | None
      openvino_devices: tuple[str, ...]
      has_directml: bool
      has_cuda: bool
      cuda_device_count: int


  def _register_cuda_dll_dirs() -> None:
      """C1 fix: ctranslate2 import 前に CUDA / cuDNN DLL の search path を注入する。

      既存 `core/recording/transcriber.py` の同等ヘルパを再利用 or 同等実装。
      Windows + nvidia-cudnn-cu12 wheel が site-packages に入っている前提で、
      `os.add_dll_directory()` を呼ぶ。失敗しても黙って戻る(後段で probe_cuda が
      (False, 0) を返すだけで、起動はブロックしない)。
      """
      try:
          from core.recording.transcriber import _register_cuda_dll_dirs as _existing
          _existing()
      except Exception:
          pass


  def probe_openvino() -> tuple[str, ...]:
      try:
          import openvino  # type: ignore[import-not-found]
      except Exception:
          return ()
      try:
          core = openvino.Core()
          return tuple(core.available_devices)
      except Exception:
          return ()


  def _run_pnputil() -> str:
      if sys.platform != "win32":
          return ""
      try:
          out = subprocess.run(
              ["pnputil", "/enum-devices", "/bus", "PCI", "/deviceids"],
              capture_output=True, text=True, timeout=10, check=False,
          )
          return out.stdout or ""
      except Exception:
          return ""


  def probe_amd_npu() -> tuple[str | None, int | None]:
      text = _run_pnputil()
      for m in _AMD_RE.finditer(text):
          dev = m.group("dev").upper()
          rev = (m.group("rev") or "").upper()
          if dev == "1502":
              return ("AMD XDNA 1", AMD_NPU_PCI_IDS["VEN_1022&DEV_1502"])
          if dev == "17F0":
              key = f"VEN_1022&DEV_17F0&REV_{rev}"
              gen = AMD_NPU_PCI_IDS.get(key)
              if gen is not None:
                  return (f"AMD XDNA {gen}", gen)
      return (None, None)


  def probe_dxcore() -> bool:
      if sys.platform != "win32":
          return False
      try:
          import onnxruntime as ort  # type: ignore[import-not-found]
          return "DmlExecutionProvider" in ort.get_available_providers()
      except Exception:
          return False


  def probe_cuda() -> tuple[bool, int]:
      """CUDA 利用可能性と device 数。C1 fix: import ctranslate2 の前に DLL search path 登録。"""
      _register_cuda_dll_dirs()
      try:
          import ctranslate2  # type: ignore[import-not-found]
          n = int(ctranslate2.get_cuda_device_count())
          return (n > 0, n)
      except Exception:
          return (False, 0)
  ```

- [ ] **Step 3: 緑確認 + コミット**
  ```
  uv run pytest tests/unit/accel/test_probe.py -v
  git add core/accel/probe.py tests/unit/accel/test_probe.py
  git commit -m "feat(accel): add sub-probes with C1 cuda dll-dir fix"
  ```

### Task 1.4: `HardwareProbe.run()` 組み立て + `NOTEBOOK_OLLAMA_SKIP_ACCEL_PROBE` ショートサーキット

- [ ] **Step 1 (RED): `tests/unit/accel/test_probe.py` 末尾に追記**
  ```python
  from core.accel.probe import HardwareProbe, HwProfile


  @pytest.mark.parametrize(
      "ov,amd,cuda,dxcore,expected_npu,expected_dgpu,expected_gen",
      [
          ((), (None, None), (True, 1), False, None, "NVIDIA CUDA dGPU", None),
          (("CPU", "GPU", "NPU"), (None, None), (False, 0), True,
           "Intel NPU", "Intel iGPU (Arc/Xe-LPG/Xe2)", None),
          (("CPU", "GPU"), (None, None), (False, 0), False,
           None, "Intel iGPU (Arc/Xe-LPG/Xe2)", None),
          ((), ("AMD XDNA 1", 1), (False, 0), True, "AMD XDNA 1", None, 1),
          ((), ("AMD XDNA 2", 2), (False, 0), True, "AMD XDNA 2", None, 2),
          ((), (None, None), (False, 0), False, None, None, None),
      ],
  )
  def test_hardware_probe_run_all_hw_profiles(
      ov, amd, cuda, dxcore, expected_npu, expected_dgpu, expected_gen, monkeypatch
  ):
      monkeypatch.delenv("NOTEBOOK_OLLAMA_SKIP_ACCEL_PROBE", raising=False)
      with (
          patch("core.accel.probe.probe_openvino", return_value=ov),
          patch("core.accel.probe.probe_amd_npu", return_value=amd),
          patch("core.accel.probe.probe_cuda", return_value=cuda),
          patch("core.accel.probe.probe_dxcore", return_value=dxcore),
      ):
          profile = HardwareProbe().run()
      assert isinstance(profile, HwProfile)
      assert profile.openvino_devices == ov
      assert profile.has_cuda == cuda[0]
      assert profile.npu == expected_npu
      assert profile.ryzen_ai_gen == expected_gen


  def test_hardware_probe_short_circuits_on_env_var(monkeypatch):
      """NOTEBOOK_OLLAMA_SKIP_ACCEL_PROBE=1 で固定 HwProfile を返す(テスト隔離)。"""
      monkeypatch.setenv("NOTEBOOK_OLLAMA_SKIP_ACCEL_PROBE", "1")
      # patch を一切しなくても pnputil/ctranslate2 が呼ばれないこと
      with (
          patch("core.accel.probe.probe_openvino") as ov,
          patch("core.accel.probe.probe_amd_npu") as amd,
          patch("core.accel.probe.probe_cuda") as cu,
          patch("core.accel.probe.probe_dxcore") as dx,
      ):
          profile = HardwareProbe().run()
      ov.assert_not_called()
      amd.assert_not_called()
      cu.assert_not_called()
      dx.assert_not_called()
      assert profile.has_cuda is False
      assert profile.cuda_device_count == 0
      assert profile.openvino_devices == ()
      assert profile.cpu_brand == "test-stub"
  ```

- [ ] **Step 2 (GREEN): `core/accel/probe.py` 末尾に `HardwareProbe` を実装**
  ```python
  import platform


  def _detect_cpu_brand() -> str:
      brand = platform.processor() or ""
      if sys.platform == "win32":
          try:
              import winreg
              key = winreg.OpenKey(
                  winreg.HKEY_LOCAL_MACHINE,
                  r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
              )
              brand = winreg.QueryValueEx(key, "ProcessorNameString")[0].strip()
          except Exception:
              pass
      return brand or "unknown"


  _STUB_PROFILE = HwProfile(
      cpu_brand="test-stub", dgpu=None, igpu=None, npu=None, vram_mb=None,
      ryzen_ai_gen=None, openvino_devices=(), has_directml=False,
      has_cuda=False, cuda_device_count=0,
  )


  class HardwareProbe:
      """4 つのサブプローブを束ねて `HwProfile` を構築する。

      環境変数 `NOTEBOOK_OLLAMA_SKIP_ACCEL_PROBE=1` で固定 stub プロファイルを返す。
      テスト隔離用(`TestClient(create_app())` の度に pnputil を shell-out しない)。
      """

      def run(self) -> HwProfile:
          if os.environ.get("NOTEBOOK_OLLAMA_SKIP_ACCEL_PROBE") == "1":
              return _STUB_PROFILE

          ov_devices = probe_openvino()
          amd_npu_name, amd_gen = probe_amd_npu()
          cuda_ok, cuda_n = probe_cuda()
          has_dml = probe_dxcore()
          cpu_brand = _detect_cpu_brand()

          igpu = "Intel iGPU (Arc/Xe-LPG/Xe2)" if "GPU" in ov_devices else None
          npu: str | None = None
          if "NPU" in ov_devices:
              npu = "Intel NPU"
          elif amd_npu_name is not None:
              npu = amd_npu_name

          dgpu = "NVIDIA CUDA dGPU" if cuda_ok else None
          return HwProfile(
              cpu_brand=cpu_brand,
              dgpu=dgpu,
              igpu=igpu,
              npu=npu,
              vram_mb=None,
              ryzen_ai_gen=amd_gen,
              openvino_devices=tuple(ov_devices),
              has_directml=has_dml,
              has_cuda=cuda_ok,
              cuda_device_count=cuda_n,
          )
  ```

- [ ] **Step 3: 緑確認 + コミット**
  ```
  uv run pytest tests/unit/accel/test_probe.py -v
  git add core/accel/probe.py tests/unit/accel/test_probe.py
  git commit -m "feat(accel): add HardwareProbe with SKIP_ACCEL_PROBE env short-circuit"
  ```

- [ ] **Step 4 (C1 smoke assertion): 開発機 clean Python で probe_cuda が True を返すこと**
  Run: `uv run python -c "from core.accel.probe import probe_cuda; ok, n = probe_cuda(); print(ok, n); assert ok and n >= 1, 'CUDA invisible to probe — C1 fix is broken'"`
  Expected: `True 1`(またはそれ以上)。**fail なら C1 fix が壊れている**(=`_register_cuda_dll_dirs` が呼ばれていない or 既存ヘルパが import 失敗)。即修正。

- [ ] **Step 5 (REFACTOR): `HardwareProbe().run()` も実機で smoke check**
  Run: `uv run python -c "from core.accel.probe import HardwareProbe; p = HardwareProbe().run(); print(p); assert p.has_cuda and p.cuda_device_count >= 1"`
  Expected: 開発機で CUDA 検出 True、device count = 1。

### Task 1.5: CUDA baseline 数値ハーネスを作る(`tests/perf/baseline.json` + `test_cuda_regression.py`)

**重要**: 以降の Sprint 2/3 で「動作回帰なし」を主張する根拠を、目視ではなく数値ゲートにする。

- [ ] **Step 1**: 現状 main(または `feat/igpu-npu-accel` ブランチ HEAD 直前)で baseline を計測
  Run(開発機の clean な uv 環境で):
  ```
  uv run python scripts/perf/capture_cuda_baseline.py --duration 30 --output tests/perf/baseline.json
  ```
  `scripts/perf/capture_cuda_baseline.py` を併せて新規作成(下記)。10 秒の WAV(例: `tests/fixtures/audio/sample_30s.wav` か `np.zeros((16000*30,), dtype=np.float32)` で擬似)を `FasterWhisperTranscriber(model_size="large-v3", device="cuda", compute_type="float16")` で `transcribe_array` し、以下を JSON で吐く:
  ```json
  {
    "captured_at": "2026-06-29T...",
    "git_sha": "<head sha>",
    "cuda_rtf": 0.12,
    "cuda_first_chunk_latency_ms": 850,
    "cuda_tokens_per_sec": 142.3,
    "model": "large-v3",
    "compute_type": "float16",
    "device": "cuda",
    "duration_s": 30
  }
  ```

- [ ] **Step 2 (RED): `tests/perf/test_cuda_regression.py` を作成**
  ```python
  import json
  from pathlib import Path

  import numpy as np
  import pytest


  BASELINE = json.loads((Path(__file__).parent / "baseline.json").read_text())
  REGRESSION_RATIO = 1.10  # 10% 悪化までは許容


  @pytest.mark.cuda
  @pytest.mark.slow
  def test_cuda_rtf_within_baseline_plus_10_percent():
      """AC-CUDA-REGRESSION numeric gate: 新 RTF ≤ baseline × 1.10。"""
      from core.recording.transcriber import FasterWhisperTranscriber
      import time

      duration_s = BASELINE["duration_s"]
      sr = 16000
      audio = np.zeros((sr * duration_s,), dtype=np.float32)

      t = FasterWhisperTranscriber(
          model_size=BASELINE["model"], device="cuda",
          compute_type=BASELINE["compute_type"],
      )
      # warm-up
      t.transcribe_array(audio[: sr * 1])
      start = time.perf_counter()
      t.transcribe_array(audio)
      elapsed = time.perf_counter() - start
      rtf = elapsed / duration_s

      max_allowed = BASELINE["cuda_rtf"] * REGRESSION_RATIO
      assert rtf <= max_allowed, (
          f"CUDA RTF regression: {rtf:.3f} > baseline {BASELINE['cuda_rtf']:.3f} × "
          f"{REGRESSION_RATIO} = {max_allowed:.3f}"
      )
  ```

- [ ] **Step 3: 開発機で gate が green になることを確認**
  Run: `uv run pytest tests/perf/test_cuda_regression.py -v -m "cuda and slow"`
  Expected: PASS(baseline 計測直後なので必ず通る)。

- [ ] **Step 4: コミット**
  ```
  mkdir -p tests/perf
  git add tests/perf/__init__.py tests/perf/baseline.json tests/perf/test_cuda_regression.py scripts/perf/capture_cuda_baseline.py
  git commit -m "test(perf): add CUDA baseline.json and regression gate (10% slack)"
  ```

### Task 1.6: `docs/testing/igpu-npu-acceptance.md` の Phase 2 用雛形作成

- [ ] **Step 1**: `docs/testing/igpu-npu-acceptance.md` を新規作成
  ```markdown
  # iGPU/NPU 受け入れテスト手順(Phase 2 用 雛形)

  本書は 10_NotebookOllama の Intel iGPU/NPU・AMD iGPU 対応(`docs/specs/2026-06-28-igpu-npu-acceleration-design.md`)を **Phase 2 で実装したとき** に実機で確認するための手順書テンプレ。

  **Phase 1 では本ファイルは雛形のみで、検証ステータスはすべて `Phase 2 未着手`。**

  開発機(NVIDIA RTX 2080 Ti / Intel i9-12900KF)には Intel iGPU/NPU・AMD Ryzen AI ハードウェアが無く、調達予定もないため、これらの実機検証は Phase 2 着手時にテスタ協力で行う想定。

  ## 検証ケース

  | ID | 環境 | 検証内容 | 状態 | 担当 |
  |---|---|---|---|---|
  | AC-INTEL-1 | Core Ultra 100/200 + NPU drv | HardwareProbe が NPU を検出 | Phase 2 未着手 | TBD |
  | AC-INTEL-2 | 同上 | STT が `openvino-whisper-npu` で起動し 5 秒発話を字幕化 | Phase 2 未着手 | TBD |
  | AC-INTEL-3 | 同上 | LLM が `ipex-llm-ollama` で qwen2.5:7b を生成開始 | Phase 2 未着手 | TBD |
  | AC-AMD-1 | Ryzen AI 300 シリーズ | HardwareProbe が pnputil で AMD NPU を検出 | Phase 2 未着手 | TBD |
  | AC-AMD-DML-1 | 同上 | LLM が DirectML 経由 Ollama Vulkan で動作 | Phase 2 未着手 | TBD |
  | AC-CUDA-REGRESSION | RTX 2080 Ti(開発機) | Planner が `faster-whisper-cuda` を選び `tests/perf/test_cuda_regression.py` が green | Phase 1 で自動化済 | dev |
  | AC-CPU-FALLBACK | GPU 無し VM | 全 CPU 経路で起動、ライブ字幕が(遅くても)動く | Phase 1 で確認 | dev |

  ## 既知制約(Phase 1+2 共通)

  - **AMD Ryzen AI NPU 用 Whisper(`amd-whispercpp-npu`)は v1 から除外**(`pywhispercpp` の継続性リスクとモデル品質検証コストのため)。AMD ユーザは DirectML 経路のみで対応する(Phase 2)。
  - **sherpa-onnx の話者分離・話者声紋 embedding は全環境で CPU 固定**(provider 切替を v1 から除外)。NVIDIA / Intel / AMD どの環境でも diarization / speaker embedding は CPU 実行される。

  ## 各ケースの実行コマンド

  (Phase 2 着手時に追記)
  ```

- [ ] **Step 2**: コミット
  ```
  git add docs/testing/igpu-npu-acceptance.md
  git commit -m "docs(accel): add Phase 2 acceptance test skeleton with v1 limitations noted"
  ```

### Sprint 1 受入条件

- [ ] `uv run pytest tests/unit/accel/ -v` 全 PASS。
- [ ] **C1 smoke**: 開発機 clean Python で `python -c "from core.accel.probe import probe_cuda; ok, n = probe_cuda(); assert ok and n >= 1"` が exit 0。
- [ ] 開発機で `HardwareProbe().run()` が CUDA を検出し、`cuda_device_count = 1`。
- [ ] `NOTEBOOK_OLLAMA_SKIP_ACCEL_PROBE=1` で `HardwareProbe().run()` が固定 stub を返し、pnputil / ctranslate2 を呼ばない(`test_hardware_probe_short_circuits_on_env_var` で担保)。
- [ ] `pyproject.toml` の `intel` / `amd` extras が空グループとして解析される(`uv sync --extra intel` エラーなし)。
- [ ] `tests/perf/baseline.json` に開発機の RTF / tok/s / first-chunk latency が固定済み、`pytest -m "cuda and slow" tests/perf/test_cuda_regression.py` が green。
- [ ] AC-CUDA-REGRESSION: 既存 `tests/unit/test_transcriber*.py` が壊れていない。

---

## Sprint 2: BackendPlanner + BackendPlan(amd-whispercpp-npu **削除**、sherpa-onnx は cpu 固定)

spec §3.1(BackendPlanner ブロック)・§4(コンポーネント別バックエンド表)・§5(BackendPlanner ルール)・§6.3(NPU 単一プロセス占有)に対応。Planner は `HwProfile + UserOverride → BackendPlan` の **純関数** とし、ハード依存を一切持たない。

**ユーザ決定の反映**:

- `amd-whispercpp-npu` を `BACKEND_IDS` から **完全に削除**。Planner の AMD STT 分岐は削除(AMD ユーザは Phase 1 では `faster-whisper-cpu`、Phase 2 で DirectML 経路が入る予定)。テストも対応削除。
- sherpa-onnx の GPU/NPU 系 ID(`sherpa-onnx-dml`, `sherpa-onnx-openvino-gpu`, `sherpa-onnx-openvino-npu`)も `BACKEND_IDS` から **完全に削除**。`sherpa-onnx-cpu` のみ残す。Diarizer / SpeakerEmbedder は全環境で CPU 固定(既知制約)。

**Files:**
- Add: `core/accel/plan.py`(`BackendPlan` + `UserOverride` + `BACKEND_IDS` dataclass、AMD/sherpa GPU 系を除外した縮小版)
- Add: `core/accel/planner.py`(`BackendPlanner.plan(hw, overrides) -> BackendPlan`)
- Add: `tests/unit/accel/test_plan.py`
- Add: `tests/unit/accel/test_planner.py`(表駆動 parametrize、削除 ID は **NOT IN** をアサート)

**Interfaces:**
- Consumes: `core.accel.probe.HwProfile`
- Produces:
  - `core.accel.plan.BackendPlan`, `BackendChoice`, `LlmChoice`, `UserOverride`
  - `core.accel.plan.BACKEND_IDS`(縮小版)
  - `core.accel.planner.BackendPlanner.plan(hw, overrides) -> BackendPlan`
  - `core.accel.planner.plan_to_log_dict(plan) -> dict[str, str]`

### Task 2.1: `BackendPlan` / `UserOverride` / `BACKEND_IDS`(縮小版)

- [ ] **Step 1 (RED): `tests/unit/accel/test_plan.py` を作成**
  ```python
  import pytest

  from core.accel.plan import (
      BACKEND_IDS, BackendChoice, BackendPlan, LlmChoice, UserOverride,
  )


  def test_backend_ids_contain_v1_kept_backends():
      expected = {
          # STT (Phase 1: cuda/cpu のみ建造可、Phase 2: intel iGPU/NPU が加わる)
          "faster-whisper-cuda", "faster-whisper-cpu",
          "openvino-whisper-igpu", "openvino-whisper-npu",
          # Diarizer / Speaker Embed (v1 は cpu のみ)
          "sherpa-onnx-cpu",
          # LLM
          "ollama-cuda", "ipex-llm-ollama", "ollama-vulkan", "openvino-genai-server",
          # Text Embedding
          "ollama-bge-m3-cpu", "ollama-bge-m3-gpu",
          "openvino-bge-m3-igpu", "openvino-bge-m3-npu",
      }
      assert expected.issubset(BACKEND_IDS)


  def test_backend_ids_excludes_amd_whispercpp_npu():
      """ユーザ決定 3: AMD NPU STT は v1 から完全除外。"""
      assert "amd-whispercpp-npu" not in BACKEND_IDS


  def test_backend_ids_excludes_sherpa_onnx_gpu_npu_variants():
      """ユーザ決定 4: sherpa-onnx GPU/NPU は v1 から完全除外。"""
      for forbidden in (
          "sherpa-onnx-dml",
          "sherpa-onnx-openvino-gpu",
          "sherpa-onnx-openvino-npu",
      ):
          assert forbidden not in BACKEND_IDS, f"{forbidden} must be excluded in v1"


  def test_user_override_default_is_all_auto():
      o = UserOverride()
      assert o.stt == "auto"
      assert o.diarize == "auto"
      assert o.speaker_embed == "auto"
      assert o.llm == "auto"
      assert o.text_embed == "auto"


  def test_backend_plan_is_frozen():
      plan = BackendPlan(
          stt=BackendChoice(id="faster-whisper-cuda", device="cuda", model="large-v3"),
          diarize=BackendChoice(id="sherpa-onnx-cpu", provider="cpu"),
          speaker_embed=BackendChoice(id="sherpa-onnx-cpu", provider="cpu"),
          llm=LlmChoice(
              id="ollama-cuda", endpoint_url="http://localhost:11434",
              display_name="Ollama (CUDA)",
          ),
          text_embed=BackendChoice(id="ollama-bge-m3-cpu", route="ollama"),
      )
      with pytest.raises(Exception):
          plan.stt = BackendChoice(id="x", device="cpu", model="m")  # type: ignore
  ```

- [ ] **Step 2 (GREEN): `core/accel/plan.py` を実装**
  ```python
  from __future__ import annotations
  from dataclasses import dataclass, field
  from typing import Any


  BACKEND_IDS: frozenset[str] = frozenset({
      # --- STT ---
      "faster-whisper-cuda", "faster-whisper-cpu",
      # Phase 2 で Factory builder が追加される予定の Intel STT(Phase 1 では Planner が
      # 選んでも Factory が明示エラーを出す。dev box は NVIDIA のみなので発火しない)
      "openvino-whisper-igpu", "openvino-whisper-npu",
      # NOTE: amd-whispercpp-npu はユーザ決定 3 により v1 から **完全削除**。
      # --- Diarizer / Speaker Embed ---
      "sherpa-onnx-cpu",
      # NOTE: sherpa-onnx-dml / -openvino-gpu / -openvino-npu はユーザ決定 4 により
      #       v1+v2 共に削除。話者分離は全環境 CPU 固定(既知制約)。
      # --- LLM ---
      "ollama-cuda", "ipex-llm-ollama", "ollama-vulkan", "openvino-genai-server",
      # --- Text Embedding ---
      "ollama-bge-m3-cpu", "ollama-bge-m3-gpu",
      "openvino-bge-m3-igpu", "openvino-bge-m3-npu",
  })


  @dataclass(frozen=True)
  class BackendChoice:
      id: str
      device: str | None = None
      model: str | None = None
      provider: str | None = None
      route: str | None = None
      extras: dict[str, Any] = field(default_factory=dict)


  @dataclass(frozen=True)
  class LlmChoice:
      id: str
      endpoint_url: str
      display_name: str


  @dataclass(frozen=True)
  class BackendPlan:
      stt: BackendChoice
      diarize: BackendChoice
      speaker_embed: BackendChoice
      llm: LlmChoice
      text_embed: BackendChoice


  @dataclass(frozen=True)
  class UserOverride:
      stt: str = "auto"
      diarize: str = "auto"
      speaker_embed: str = "auto"
      llm: str = "auto"
      text_embed: str = "auto"
  ```

- [ ] **Step 3: 緑確認 + コミット**
  ```
  uv run pytest tests/unit/accel/test_plan.py -v
  git add core/accel/plan.py tests/unit/accel/test_plan.py
  git commit -m "feat(accel): add BackendPlan dataclasses (amd-npu and sherpa-gpu excluded)"
  ```

### Task 2.2: `BackendPlanner.plan()`(sherpa-onnx は cpu 固定、AMD STT は CPU フォールバック)

- [ ] **Step 1 (RED): `tests/unit/accel/test_planner.py` を作成**
  ```python
  import pytest

  from core.accel.plan import UserOverride
  from core.accel.planner import BackendPlanner
  from core.accel.probe import HwProfile


  def _profile(**overrides):
      base = dict(
          cpu_brand="x", dgpu=None, igpu=None, npu=None, vram_mb=None,
          ryzen_ai_gen=None, openvino_devices=(), has_directml=False,
          has_cuda=False, cuda_device_count=0,
      )
      base.update(overrides)
      return HwProfile(**base)


  class TestAutoStt:
      def test_nvidia_picks_faster_whisper_cuda(self):
          hw = _profile(dgpu="NVIDIA CUDA dGPU", has_cuda=True, cuda_device_count=1)
          plan = BackendPlanner().plan(hw, UserOverride())
          assert plan.stt.id == "faster-whisper-cuda"
          assert plan.stt.device == "cuda"

      def test_intel_npu_preferred_over_igpu(self):
          hw = _profile(
              npu="Intel NPU", igpu="Intel iGPU (Arc/Xe-LPG/Xe2)",
              openvino_devices=("CPU", "GPU", "NPU"),
          )
          plan = BackendPlanner().plan(hw, UserOverride())
          assert plan.stt.id == "openvino-whisper-npu"

      def test_intel_igpu_only(self):
          hw = _profile(
              igpu="Intel iGPU (Arc/Xe-LPG/Xe2)", openvino_devices=("CPU", "GPU"),
          )
          plan = BackendPlanner().plan(hw, UserOverride())
          assert plan.stt.id == "openvino-whisper-igpu"

      def test_amd_falls_back_to_cpu_in_v1(self):
          """ユーザ決定 3: amd-whispercpp-npu は v1 で削除。AMD は CPU 経路で start。"""
          hw = _profile(npu="AMD XDNA 2", ryzen_ai_gen=2)
          plan = BackendPlanner().plan(hw, UserOverride())
          assert plan.stt.id == "faster-whisper-cpu"
          assert plan.stt.id != "amd-whispercpp-npu"  # 念押し

      def test_no_accel_falls_back_to_cpu_medium_int8(self):
          plan = BackendPlanner().plan(_profile(), UserOverride())
          assert plan.stt.id == "faster-whisper-cpu"
          assert plan.stt.model == "medium"


  class TestAutoDiarizer:
      """ユーザ決定 4: sherpa-onnx は v1+v2 全環境 cpu 固定。"""

      @pytest.mark.parametrize("hw_kwargs", [
          {"dgpu": "NVIDIA CUDA dGPU", "has_cuda": True, "cuda_device_count": 1},
          {"npu": "Intel NPU", "openvino_devices": ("CPU", "GPU", "NPU")},
          {"igpu": "Intel iGPU", "openvino_devices": ("CPU", "GPU")},
          {"npu": "AMD XDNA 2", "ryzen_ai_gen": 2, "has_directml": True},
          {},  # CPU only
      ])
      def test_diarizer_is_always_cpu(self, hw_kwargs):
          hw = _profile(**hw_kwargs)
          plan = BackendPlanner().plan(hw, UserOverride())
          assert plan.diarize.id == "sherpa-onnx-cpu"
          assert plan.speaker_embed.id == "sherpa-onnx-cpu"


  class TestAutoLlm:
      def test_nvidia_picks_ollama_cuda(self):
          hw = _profile(dgpu="NVIDIA CUDA dGPU", has_cuda=True, cuda_device_count=1)
          plan = BackendPlanner().plan(hw, UserOverride())
          assert plan.llm.id == "ollama-cuda"
          assert plan.llm.endpoint_url == "http://localhost:11434"

      def test_intel_igpu_picks_ipex_llm(self):
          hw = _profile(igpu="Intel iGPU", openvino_devices=("CPU", "GPU"))
          plan = BackendPlanner().plan(hw, UserOverride())
          assert plan.llm.id == "ipex-llm-ollama"

      def test_amd_picks_ollama_vulkan(self):
          hw = _profile(npu="AMD XDNA 2", ryzen_ai_gen=2)
          plan = BackendPlanner().plan(hw, UserOverride())
          assert plan.llm.id == "ollama-vulkan"


  class TestNpuSingleProcessConstraint:
      def test_intel_npu_used_by_stt_not_by_llm(self):
          hw = _profile(
              npu="Intel NPU", igpu="Intel iGPU",
              openvino_devices=("CPU", "GPU", "NPU"),
          )
          plan = BackendPlanner().plan(hw, UserOverride())
          assert plan.stt.id == "openvino-whisper-npu"
          assert plan.llm.id == "ipex-llm-ollama"


  class TestUserOverride:
      def test_manual_override_forces_backend(self):
          hw = _profile(dgpu="NVIDIA CUDA dGPU", has_cuda=True, cuda_device_count=1)
          plan = BackendPlanner().plan(hw, UserOverride(stt="faster-whisper-cpu"))
          assert plan.stt.id == "faster-whisper-cpu"

      def test_invalid_override_id_raises(self):
          with pytest.raises(ValueError, match="unknown backend id"):
              BackendPlanner().plan(_profile(), UserOverride(stt="does-not-exist"))

      def test_amd_npu_override_rejected_in_v1(self):
          """ユーザ決定 3 を override 経路でも担保。"""
          with pytest.raises(ValueError, match="unknown backend id"):
              BackendPlanner().plan(_profile(), UserOverride(stt="amd-whispercpp-npu"))

      def test_sherpa_dml_override_rejected_in_v1(self):
          with pytest.raises(ValueError, match="unknown backend id"):
              BackendPlanner().plan(_profile(), UserOverride(diarize="sherpa-onnx-dml"))


  class TestTextEmbedDefault:
      def test_default_text_embed_is_ollama_cpu(self):
          hw = _profile(dgpu="NVIDIA CUDA dGPU", has_cuda=True, cuda_device_count=1)
          plan = BackendPlanner().plan(hw, UserOverride())
          assert plan.text_embed.id == "ollama-bge-m3-cpu"
          assert plan.text_embed.route == "ollama"

      def test_intel_npu_opts_text_embed_to_openvino_igpu(self):
          hw = _profile(npu="Intel NPU", openvino_devices=("CPU", "GPU", "NPU"))
          plan = BackendPlanner().plan(hw, UserOverride())
          assert plan.text_embed.id == "openvino-bge-m3-igpu"
          assert plan.text_embed.route == "openvino-direct"


  def test_planner_does_not_silently_fallback_llm():
      """spec §6.1: ユーザの LLM 選択は黙って変えない。"""
      hw = _profile(dgpu="NVIDIA CUDA dGPU", has_cuda=True, cuda_device_count=1)
      plan = BackendPlanner().plan(hw, UserOverride(llm="ipex-llm-ollama"))
      assert plan.llm.id == "ipex-llm-ollama"
  ```

- [ ] **Step 2 (GREEN): `core/accel/planner.py` を実装**
  ```python
  from __future__ import annotations

  from core.accel.plan import (
      BACKEND_IDS, BackendChoice, BackendPlan, LlmChoice, UserOverride,
  )
  from core.accel.probe import HwProfile

  _OLLAMA_LOCAL_URL = "http://localhost:11434"


  class BackendPlanner:
      """純関数(ハード依存なし)。HwProfile + UserOverride → BackendPlan。

      v1 制約:
      - amd-whispercpp-npu は BACKEND_IDS から削除済み(ユーザ決定 3)
      - sherpa-onnx-* は cpu のみ。GPU/NPU 系は BACKEND_IDS から削除済み(ユーザ決定 4)
      """

      def plan(self, hw: HwProfile, overrides: UserOverride) -> BackendPlan:
          for field_name in ("stt", "diarize", "speaker_embed", "llm", "text_embed"):
              v = getattr(overrides, field_name)
              if v != "auto" and v not in BACKEND_IDS:
                  raise ValueError(f"unknown backend id: {v} (field={field_name})")

          stt = self._pick_stt(hw, overrides.stt)
          stt_uses_intel_npu = stt.id == "openvino-whisper-npu"

          llm = self._pick_llm(hw, overrides.llm)
          diarize = self._pick_diarize(overrides.diarize)
          speaker_embed = self._pick_speaker_embed(overrides.speaker_embed)
          text_embed = self._pick_text_embed(
              hw, overrides.text_embed, avoid_intel_npu=stt_uses_intel_npu
          )
          return BackendPlan(
              stt=stt, diarize=diarize, speaker_embed=speaker_embed,
              llm=llm, text_embed=text_embed,
          )

      def _pick_stt(self, hw: HwProfile, override: str) -> BackendChoice:
          if override != "auto":
              return _stt_choice_for_id(override)
          if hw.has_cuda:
              return BackendChoice(
                  id="faster-whisper-cuda", device="cuda", model="large-v3",
              )
          if hw.npu == "Intel NPU":
              return BackendChoice(
                  id="openvino-whisper-npu", device="NPU",
                  model="distil-whisper-large-v2-int8",
              )
          if "GPU" in hw.openvino_devices:
              return BackendChoice(
                  id="openvino-whisper-igpu", device="GPU",
                  model="distil-whisper-large-v3-int8",
              )
          # ユーザ決定 3: AMD は v1 では amd-whispercpp-npu を持たない。CPU 経路に落とす。
          return BackendChoice(
              id="faster-whisper-cpu", device="cpu", model="medium",
          )

      def _pick_llm(self, hw: HwProfile, override: str) -> LlmChoice:
          if override != "auto":
              return _llm_choice_for_id(override)
          if hw.has_cuda:
              return LlmChoice(
                  id="ollama-cuda", endpoint_url=_OLLAMA_LOCAL_URL,
                  display_name="Ollama (CUDA)",
              )
          if "GPU" in hw.openvino_devices:
              return LlmChoice(
                  id="ipex-llm-ollama", endpoint_url=_OLLAMA_LOCAL_URL,
                  display_name="IPEX-LLM Ollama (Intel iGPU)",
              )
          if hw.ryzen_ai_gen in (1, 2):
              return LlmChoice(
                  id="ollama-vulkan", endpoint_url=_OLLAMA_LOCAL_URL,
                  display_name="Ollama (Vulkan, AMD iGPU)",
              )
          return LlmChoice(
              id="ollama-cuda", endpoint_url=_OLLAMA_LOCAL_URL,
              display_name="Ollama (CPU fallback)",
          )

      def _pick_diarize(self, override: str) -> BackendChoice:
          """ユーザ決定 4: sherpa-onnx は全環境 cpu 固定。"""
          if override != "auto" and override != "sherpa-onnx-cpu":
              raise ValueError(f"unknown backend id: {override} (field=diarize)")
          return BackendChoice(id="sherpa-onnx-cpu", provider="cpu")

      def _pick_speaker_embed(self, override: str) -> BackendChoice:
          if override != "auto" and override != "sherpa-onnx-cpu":
              raise ValueError(f"unknown backend id: {override} (field=speaker_embed)")
          return BackendChoice(id="sherpa-onnx-cpu", provider="cpu")

      def _pick_text_embed(
          self, hw: HwProfile, override: str, *, avoid_intel_npu: bool
      ) -> BackendChoice:
          if override != "auto":
              return _text_embed_choice_for_id(override)
          if "GPU" in hw.openvino_devices:
              return BackendChoice(id="openvino-bge-m3-igpu", route="openvino-direct")
          if "NPU" in hw.openvino_devices and not avoid_intel_npu:
              return BackendChoice(id="openvino-bge-m3-npu", route="openvino-direct")
          return BackendChoice(id="ollama-bge-m3-cpu", route="ollama")


  def _stt_choice_for_id(id: str) -> BackendChoice:
      table = {
          "faster-whisper-cuda": BackendChoice(id=id, device="cuda", model="large-v3"),
          "faster-whisper-cpu": BackendChoice(id=id, device="cpu", model="medium"),
          "openvino-whisper-igpu": BackendChoice(
              id=id, device="GPU", model="distil-whisper-large-v3-int8"
          ),
          "openvino-whisper-npu": BackendChoice(
              id=id, device="NPU", model="distil-whisper-large-v2-int8"
          ),
      }
      if id not in table:
          raise ValueError(f"unknown backend id: {id} (field=stt)")
      return table[id]


  def _llm_choice_for_id(id: str) -> LlmChoice:
      table = {
          "ollama-cuda": LlmChoice(id=id, endpoint_url=_OLLAMA_LOCAL_URL,
                                    display_name="Ollama (CUDA)"),
          "ipex-llm-ollama": LlmChoice(id=id, endpoint_url=_OLLAMA_LOCAL_URL,
                                        display_name="IPEX-LLM Ollama"),
          "ollama-vulkan": LlmChoice(id=id, endpoint_url=_OLLAMA_LOCAL_URL,
                                      display_name="Ollama (Vulkan)"),
          "openvino-genai-server": LlmChoice(
              id=id, endpoint_url="http://localhost:8000",
              display_name="OpenVINO GenAI Server",
          ),
      }
      if id not in table:
          raise ValueError(f"unknown backend id: {id} (field=llm)")
      return table[id]


  def _text_embed_choice_for_id(id: str) -> BackendChoice:
      table = {
          "ollama-bge-m3-cpu": BackendChoice(id=id, route="ollama"),
          "ollama-bge-m3-gpu": BackendChoice(id=id, route="ollama"),
          "openvino-bge-m3-igpu": BackendChoice(id=id, route="openvino-direct"),
          "openvino-bge-m3-npu": BackendChoice(id=id, route="openvino-direct"),
      }
      if id not in table:
          raise ValueError(f"unknown backend id: {id} (field=text_embed)")
      return table[id]


  def plan_to_log_dict(plan: BackendPlan) -> dict[str, str]:
      return {
          "stt": plan.stt.id,
          "diarize": plan.diarize.id,
          "speaker_embed": plan.speaker_embed.id,
          "llm": plan.llm.id,
          "text_embed": plan.text_embed.id,
      }
  ```

- [ ] **Step 3: 緑確認 + コミット**
  ```
  uv run pytest tests/unit/accel/test_planner.py -v
  git add core/accel/planner.py tests/unit/accel/test_planner.py
  git commit -m "feat(accel): add BackendPlanner with v1 constraints (no amd-npu, sherpa cpu-only)"
  ```

### Task 2.3: 開発機 smoke check(Planner が CUDA を選ぶこと)

- [ ] **Step 1**: 開発機実機で確認
  Run: `uv run python -c "from core.accel.probe import HardwareProbe; from core.accel.planner import BackendPlanner, plan_to_log_dict; from core.accel.plan import UserOverride; p = BackendPlanner().plan(HardwareProbe().run(), UserOverride()); print(plan_to_log_dict(p))"`
  Expected: `{'stt': 'faster-whisper-cuda', 'diarize': 'sherpa-onnx-cpu', 'speaker_embed': 'sherpa-onnx-cpu', 'llm': 'ollama-cuda', 'text_embed': 'ollama-bge-m3-cpu'}`

### Sprint 2 受入条件

- [ ] `uv run pytest tests/unit/accel/ -v` 全 PASS。
- [ ] Planner は `HardwareProbe` を直接 import しない(`HwProfile` を引数で受ける)。`grep -n "HardwareProbe\|probe_cuda\|pnputil" core/accel/planner.py` が 0 件。
- [ ] `amd-whispercpp-npu` が `BACKEND_IDS` に **存在しない**(`test_backend_ids_excludes_amd_whispercpp_npu`)。
- [ ] `sherpa-onnx-dml`/`-openvino-gpu`/`-openvino-npu` が `BACKEND_IDS` に **存在しない**(`test_backend_ids_excludes_sherpa_onnx_gpu_npu_variants`)。
- [ ] 全 HW プロファイルで `plan.diarize.id == "sherpa-onnx-cpu"` かつ `plan.speaker_embed.id == "sherpa-onnx-cpu"`(`TestAutoDiarizer` parametrize)。
- [ ] override に未知 ID を渡すと `ValueError("unknown backend id: ...")`(削除済み ID も含む)。
- [ ] AC-CUDA-REGRESSION: 開発機の Planner 出力が `stt=faster-whisper-cuda` / `llm=ollama-cuda` / `text_embed=ollama-bge-m3-cpu`。

---

## Sprint 3: whisper_postprocess 抽出 + Settings 拡張 + BackendFactory skeleton + DI 結線 + read-only Acceleration タブ + CUDA 回帰ゲート最終確認

spec §3.1(BackendFactory)・§5.1(起動シーケンス)・§6(Settings 拡張)・§7(既存コードへの結線箇所)・§7.1(設定画面拡張)に対応。

**Sprint の 3 つの軸**:

1. **C2 fix(extract refactor only)**: `core/recording/transcriber.py` に埋め込まれている live-caption postprocess(RMS floor / VAD / no_speech filtering / `_HALLUCINATION_NORM` blocklist)を `core/recording/whisper_postprocess.py` に切り出す。**Phase 1 では振る舞いは 100% 不変**。Phase 2 で `OpenVINOWhisperTranscriber` 等を追加するとき、これらの postprocess 関数を再利用できる土台を作る。これを怠ると Phase 2 で transcriber 実装ごとに同等ロジックを各自実装することになり、片方だけ幻覚抑制が抜ける事故が起きる(adversarial review の C2 指摘)。
2. **Settings + Factory + DI**: `AppConfig` に `transcriber_backend` 等の `"auto"` 既定フィールドを追加し、`apps/api/main.py` の lifespan で `HardwareProbe → BackendPlanner → BackendFactory` を走らせ、結果を `ctx.transcriber` 等に格納。**Phase 1 builder は CUDA/CPU 系のみ**。Phase 2 ID(`openvino-whisper-igpu` 等)を渡されたら明示エラー。
3. **Read-only Acceleration タブ**: `/settings` に「Acceleration」タブを追加し、検出 HW と Plan を **表示のみ** で出す。`<select>` ドロップダウンも `[Apply]` ボタンも置かない(ユーザ決定: 「Override knobs come in Phase 2」)。**GUI 変更につき Playwright MCP の実機スクショ必須**。

**Files:**
- Add: `core/recording/whisper_postprocess.py`(extract 先)
- Modify: `core/recording/transcriber.py`(postprocess 関数を whisper_postprocess から import に変更、振る舞い不変)
- Add: `tests/unit/test_whisper_postprocess.py`(抽出した関数の単体テスト)
- Modify: `core/config.py`(`OllamaSettings.runtime_backend` / `text_embed_backend`、`AudioSettings.transcriber_backend` / `diarizer_backend` / `speaker_embed_backend` 追加、すべて `"auto"` 既定)
- Add: `core/accel/factory.py`(Phase 1 builder のみ。Phase 2 ID には「Phase 2 not yet implemented」を明示)
- Modify: `apps/api/main.py` / `apps/api/dependencies.py`(起動時に `HardwareProbe → Planner → Factory.build → ctx に格納`)
- Modify: `apps/api/routers/settings.py`(`GET /api/settings/acceleration` のみ追加。`PUT` は Phase 2)
- Modify: `apps/api/schemas/settings.py`(`AccelerationStatusSchema`)
- Add: `tests/unit/accel/test_factory.py`
- Add: `tests/integration/test_api/test_settings_acceleration.py`(`NOTEBOOK_OLLAMA_SKIP_ACCEL_PROBE=1` を conftest で立てる)
- Add: `tests/unit/test_config_backends.py`
- Modify: `apps/web/src/lib/api/types.ts`(`HardwareStatus`, `PlanSummary`, `AccelerationStatus` 追加)
- Modify: `apps/web/src/lib/api/settings.ts`(`getAcceleration()` のみ追加。`putAcceleration` は Phase 2)
- Modify: `apps/web/src/lib/stores/settings.svelte.ts`(`accelerationStatus` state + `loadAcceleration`)
- Add: `apps/web/src/lib/components/AccelerationPanel.svelte`(**read-only**)
- Modify: `apps/web/src/routes/settings/+page.svelte`(`section==='acceleration'` 追加)

### Task 3.1: C2 fix — whisper postprocess を `core/recording/whisper_postprocess.py` に抽出

**重要**: 本 Task は **振る舞いを 100% 維持** する extract refactor。`core/recording/transcriber.py` の `transcribe_array` の内部ロジックは変えず、ヘルパ関数だけを別モジュールに切り出す。

- [ ] **Step 1 (baseline 確認)**: 既存 transcriber テストを実行
  ```
  uv run pytest tests/unit/test_transcriber*.py -v --tb=short
  ```
  Expected: 全 PASS(現状ベースライン)。

- [ ] **Step 2 (RED): `tests/unit/test_whisper_postprocess.py` を作成**
  - `core/recording/transcriber.py` に現状埋め込まれている関数・定数(具体的には RMS floor 判定、VAD 判定、`no_speech_prob` フィルタ閾値、`_HALLUCINATION_NORM` 集合とその正規化 / マッチ関数)を `whisper_postprocess` から import するテストを書く。例:
  ```python
  import numpy as np
  import pytest

  from core.recording.whisper_postprocess import (
      HALLUCINATION_NORM, apply_rms_floor, is_voice,
      normalize_for_hallucination_check, should_filter_hallucination,
  )


  def test_hallucination_norm_contains_canonical_phrases():
      # 既存 _HALLUCINATION_NORM(transcriber.py 内)に含まれる代表句が公開される
      assert "ご視聴ありがとうございました" in {
          normalize_for_hallucination_check(s) for s in HALLUCINATION_NORM
      } or "ご視聴ありがとうございました" in HALLUCINATION_NORM

  def test_should_filter_hallucination_blocks_known_phrase():
      assert should_filter_hallucination("ご視聴ありがとうございました") is True
      assert should_filter_hallucination("これは普通の発話です") is False

  def test_is_voice_false_for_silence():
      audio = np.zeros(16000, dtype=np.float32)
      assert is_voice(audio, sample_rate=16000) is False

  def test_is_voice_true_for_loud_signal():
      audio = (np.random.RandomState(42).randn(16000) * 0.3).astype(np.float32)
      assert is_voice(audio, sample_rate=16000) is True

  def test_apply_rms_floor_returns_empty_for_silence():
      audio = np.zeros(16000, dtype=np.float32)
      assert apply_rms_floor(audio) == []  # 既存挙動: silence は空 segment
  ```
  Run: `uv run pytest tests/unit/test_whisper_postprocess.py -v`
  Expected: FAIL(`core.recording.whisper_postprocess` 未存在)。

- [ ] **Step 3 (GREEN): `core/recording/whisper_postprocess.py` を作成し、`transcriber.py` から該当ロジックを切り出して移動**
  - 既存 `core/recording/transcriber.py` を `Grep` で確認(`_HALLUCINATION_NORM`, `_rms`, `_is_voice`, `no_speech` 周辺):
    ```
    grep -nE "_HALLUCINATION_NORM|_rms|_is_voice|no_speech_prob|hallucinat" core/recording/transcriber.py
    ```
  - 該当関数・定数を `whisper_postprocess.py` に移動(関数名は `_` プレフィックスを外して公開化、または内部から re-export)。
  - `transcriber.py` 側はこれらを `from core.recording.whisper_postprocess import ...` に置き換える。
  - **構造的に同じコード** であることを確認(振る舞い不変)。

- [ ] **Step 4 (REGRESSION GATE)**: 既存 transcriber テスト + perf gate 再実行
  ```
  uv run pytest tests/unit/test_transcriber*.py tests/unit/test_whisper_postprocess.py -v
  uv run pytest -m "cuda and slow" tests/perf/test_cuda_regression.py -v
  ```
  Expected: 既存テスト全 PASS、perf gate も green(10% slack 内)。

- [ ] **Step 5: コミット**
  ```
  git add core/recording/whisper_postprocess.py core/recording/transcriber.py tests/unit/test_whisper_postprocess.py
  git commit -m "refactor(recording): extract whisper postprocess to whisper_postprocess.py (no behavior change)"
  ```

### Task 3.2: `AppConfig` に backend 上書きフィールド追加(後方互換 / `"auto"` 既定)

- [ ] **Step 1 (RED): `tests/unit/test_config_backends.py` を作成**
  ```python
  from core.config import AppConfig, AudioSettings, OllamaSettings


  def test_default_backends_all_auto(tmp_path, monkeypatch):
      monkeypatch.setenv("NOTEBOOK_OLLAMA_DATA_DIR", str(tmp_path))
      cfg = AppConfig()
      assert cfg.audio.transcriber_backend == "auto"
      assert cfg.audio.diarizer_backend == "auto"
      assert cfg.audio.speaker_embed_backend == "auto"
      assert cfg.ollama.runtime_backend == "auto"
      assert cfg.ollama.text_embed_backend == "auto"


  def test_existing_settings_json_without_new_fields_still_loads():
      audio = AudioSettings(whisper_model="large-v3", device="cuda")
      assert audio.transcriber_backend == "auto"
      ollama = OllamaSettings(endpoint="http://localhost:11434")
      assert ollama.runtime_backend == "auto"
  ```

- [ ] **Step 2 (GREEN): `core/config.py` を編集**
  - `OllamaSettings`:
    ```python
    runtime_backend: str = "auto"
    text_embed_backend: str = "auto"
    ```
  - `AudioSettings`:
    ```python
    transcriber_backend: str = "auto"
    diarizer_backend: str = "auto"
    speaker_embed_backend: str = "auto"
    ```

- [ ] **Step 3: 緑確認 + 既存 settings 統合テストが壊れていないか**
  ```
  uv run pytest tests/unit/test_config_backends.py tests/integration/test_api/test_settings_api.py tests/integration/test_settings_audio.py -v
  git add core/config.py tests/unit/test_config_backends.py
  git commit -m "feat(config): add backend override fields with auto default (backward compatible)"
  ```

### Task 3.3: `BackendFactory` skeleton(Phase 1 builder のみ。Phase 2 ID は明示エラー)

- [ ] **Step 1 (RED): `tests/unit/accel/test_factory.py` を作成**
  ```python
  from unittest.mock import MagicMock, patch

  import pytest

  from core.accel.factory import BackendFactory, BuiltBackends
  from core.accel.plan import BackendChoice, BackendPlan, LlmChoice


  def _cuda_plan() -> BackendPlan:
      return BackendPlan(
          stt=BackendChoice(id="faster-whisper-cuda", device="cuda", model="large-v3"),
          diarize=BackendChoice(id="sherpa-onnx-cpu", provider="cpu"),
          speaker_embed=BackendChoice(id="sherpa-onnx-cpu", provider="cpu"),
          llm=LlmChoice(
              id="ollama-cuda", endpoint_url="http://localhost:11434",
              display_name="Ollama (CUDA)",
          ),
          text_embed=BackendChoice(id="ollama-bge-m3-cpu", route="ollama"),
      )


  def test_factory_build_cuda_plan_returns_builtbackends(tmp_path):
      with (
          patch("core.accel.factory._build_transcriber") as t,
          patch("core.accel.factory._build_diarizer") as d,
          patch("core.accel.factory._build_speaker_embedder") as se,
          patch("core.accel.factory._build_ollama_gateway") as og,
          patch("core.accel.factory._build_text_embedder") as te,
      ):
          t.return_value = MagicMock()
          d.return_value = MagicMock()
          se.return_value = MagicMock()
          og.return_value = MagicMock()
          te.return_value = MagicMock()
          built = BackendFactory().build(_cuda_plan(), config=MagicMock(data_dir=tmp_path))
      assert isinstance(built, BuiltBackends)
      assert built.effective_plan == _cuda_plan()


  def test_factory_raises_on_phase2_only_stt_id(tmp_path):
      """Phase 2 ID(openvino-whisper-igpu)は Phase 1 で明示エラー(silent fail 防止)。"""
      plan = _cuda_plan()
      bad = BackendPlan(
          stt=BackendChoice(id="openvino-whisper-igpu", device="GPU", model="distil"),
          diarize=plan.diarize, speaker_embed=plan.speaker_embed,
          llm=plan.llm, text_embed=plan.text_embed,
      )
      with pytest.raises(NotImplementedError, match="Phase 2"):
          BackendFactory().build(bad, config=MagicMock(data_dir=tmp_path))


  def test_factory_raises_on_unknown_id(tmp_path):
      plan = _cuda_plan()
      bad = BackendPlan(
          stt=BackendChoice(id="not-registered", device="cpu"),
          diarize=plan.diarize, speaker_embed=plan.speaker_embed,
          llm=plan.llm, text_embed=plan.text_embed,
      )
      with pytest.raises(ValueError, match="no STT builder"):
          BackendFactory().build(bad, config=MagicMock(data_dir=tmp_path))
  ```

- [ ] **Step 2 (GREEN): `core/accel/factory.py` を作成**
  ```python
  from __future__ import annotations

  from dataclasses import dataclass
  from pathlib import Path
  from typing import Any

  from core.accel.plan import BackendChoice, BackendPlan, LlmChoice


  _PHASE_2_STT_IDS = frozenset({"openvino-whisper-igpu", "openvino-whisper-npu"})
  _PHASE_2_LLM_IDS = frozenset({"ipex-llm-ollama", "ollama-vulkan", "openvino-genai-server"})
  _PHASE_2_TEXT_EMBED_IDS = frozenset({
      "ollama-bge-m3-gpu", "openvino-bge-m3-igpu", "openvino-bge-m3-npu",
  })


  @dataclass(frozen=True)
  class BuiltBackends:
      transcriber: Any
      diarizer: Any
      speaker_embedder: Any
      text_embedder: Any
      ollama_gateway: Any
      effective_plan: BackendPlan


  class BackendFactory:
      """Phase 1: CUDA + CPU builder のみ実装。Phase 2 ID は NotImplementedError。"""

      def build(self, plan: BackendPlan, *, config: Any) -> BuiltBackends:
          transcriber = _build_transcriber(plan.stt, config)
          diarizer = _build_diarizer(plan.diarize, config)
          speaker_embedder = _build_speaker_embedder(plan.speaker_embed, config)
          ollama_gateway = _build_ollama_gateway(plan.llm, config)
          text_embedder = _build_text_embedder(
              plan.text_embed, config, ollama_gateway=ollama_gateway
          )
          return BuiltBackends(
              transcriber=transcriber,
              diarizer=diarizer,
              speaker_embedder=speaker_embedder,
              text_embedder=text_embedder,
              ollama_gateway=ollama_gateway,
              effective_plan=plan,
          )


  def _build_transcriber(choice: BackendChoice, config: Any) -> Any:
      if choice.id == "faster-whisper-cuda":
          from core.recording.transcriber import Transcriber
          return Transcriber(
              model_size=choice.model or "large-v3",
              device="cuda", compute_type="float16",
          )
      if choice.id == "faster-whisper-cpu":
          from core.recording.transcriber import Transcriber
          return Transcriber(
              model_size=choice.model or "medium",
              device="cpu", compute_type="int8",
          )
      if choice.id in _PHASE_2_STT_IDS:
          raise NotImplementedError(
              f"STT backend '{choice.id}' is Phase 2 — not yet implemented. "
              f"Use 'faster-whisper-cuda' or 'faster-whisper-cpu' for now."
          )
      raise ValueError(f"no STT builder registered for id={choice.id}")


  def _build_diarizer(choice: BackendChoice, config: Any) -> Any:
      if choice.id == "sherpa-onnx-cpu":
          return _make_sherpa_diarizer(choice, config)
      raise ValueError(f"no diarizer builder registered for id={choice.id}")


  def _build_speaker_embedder(choice: BackendChoice, config: Any) -> Any:
      if choice.id == "sherpa-onnx-cpu":
          return _make_sherpa_speaker_embedder(choice, config)
      raise ValueError(f"no speaker_embedder builder registered for id={choice.id}")


  def _build_ollama_gateway(choice: LlmChoice, config: Any) -> Any:
      if choice.id == "ollama-cuda":
          from core.ollama.client import OllamaClient
          from core.ollama.gateway import OllamaGateway
          client = OllamaClient(
              endpoint=choice.endpoint_url,
              timeout=config.ollama.request_timeout_seconds,
          )
          return OllamaGateway(
              client=client,
              embedding_options=config.ollama.embedding_options,
          )
      if choice.id in _PHASE_2_LLM_IDS:
          raise NotImplementedError(
              f"LLM backend '{choice.id}' is Phase 2 — not yet implemented. "
              f"Use 'ollama-cuda' (which also covers CPU fallback) for now."
          )
      raise ValueError(f"no LLM builder registered for id={choice.id}")


  def _build_text_embedder(choice: BackendChoice, config: Any, *, ollama_gateway: Any) -> Any:
      if choice.id == "ollama-bge-m3-cpu":
          return _OllamaTextEmbedder(gateway=ollama_gateway, model=config.ollama.embedding_model)
      if choice.id in _PHASE_2_TEXT_EMBED_IDS:
          raise NotImplementedError(
              f"text embed backend '{choice.id}' is Phase 2 — not yet implemented. "
              f"Use 'ollama-bge-m3-cpu' (NaN-bug-safe) for now."
          )
      raise ValueError(f"no text_embedder builder registered for id={choice.id}")


  def _resolve_diarizer_models(config: Any) -> tuple[Path, Path]:
      base = Path(config.data_dir) / "models"
      seg = config.audio.diarizer_segmentation_model or str(
          base / "sherpa-onnx-pyannote-segmentation-3-0" / "model.onnx"
      )
      emb = config.audio.diarizer_embedding_model or str(
          base / "3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx"
      )
      return Path(seg), Path(emb)


  def _make_sherpa_diarizer(choice: BackendChoice, config: Any):
      from core.recording.diarizer import SherpaDiarizer
      seg, emb = _resolve_diarizer_models(config)
      return SherpaDiarizer(
          segmentation_model=seg,
          embedding_model=emb,
          threshold=config.audio.diarizer_threshold,
      )


  def _make_sherpa_speaker_embedder(choice: BackendChoice, config: Any):
      from core.recording.embeddings import SpeakerEmbedder
      _seg, emb = _resolve_diarizer_models(config)
      return SpeakerEmbedder(model_path=emb)


  class _OllamaTextEmbedder:
      def __init__(self, *, gateway: Any, model: str) -> None:
          self._gateway = gateway
          self._model = model

      async def embed(self, text: str) -> list[float]:
          return await self._gateway.embed(model=self._model, text=text)
  ```

- [ ] **Step 3: 緑確認 + コミット**
  ```
  uv run pytest tests/unit/accel/test_factory.py -v
  git add core/accel/factory.py tests/unit/accel/test_factory.py
  git commit -m "feat(accel): add BackendFactory Phase-1 skeleton (cuda/cpu only, phase-2 NotImplementedError)"
  ```

### Task 3.4: `apps/api/main.py` lifespan で probe→planner→factory + `GET /api/settings/acceleration`

- [ ] **Step 1 (RED): `tests/integration/test_api/test_settings_acceleration.py` を作成**
  ```python
  from __future__ import annotations

  import pytest
  from fastapi.testclient import TestClient

  from apps.api.main import create_app


  @pytest.fixture(autouse=True)
  def _skip_accel_probe(monkeypatch):
      """テスト隔離: pnputil / ctranslate2 を毎回呼ばない。"""
      monkeypatch.setenv("NOTEBOOK_OLLAMA_SKIP_ACCEL_PROBE", "1")


  def test_get_acceleration_returns_hw_and_plan(memory_data_dir):
      with TestClient(create_app()) as client:
          r = client.get("/api/settings/acceleration")
          assert r.status_code == 200
          body = r.json()
      assert "hardware" in body
      assert "plan" in body
      assert set(body["plan"].keys()) == {
          "stt", "diarize", "speaker_embed", "llm", "text_embed"
      }
      assert "openvino_devices" in body["hardware"]
      assert "has_cuda" in body["hardware"]
      # SKIP_ACCEL_PROBE=1 のため stub が返る
      assert body["hardware"]["has_cuda"] is False
      assert body["plan"]["stt"] == "faster-whisper-cpu"
      assert body["plan"]["diarize"] == "sherpa-onnx-cpu"
  ```

- [ ] **Step 2 (GREEN): `apps/api/schemas/settings.py` に `AccelerationStatusSchema` を追加**
  ```python
  class HardwareStatusSchema(BaseModel):
      cpu_brand: str
      dgpu: str | None
      igpu: str | None
      npu: str | None
      openvino_devices: list[str]
      has_directml: bool
      has_cuda: bool
      cuda_device_count: int
      ryzen_ai_gen: int | None


  class PlanSummarySchema(BaseModel):
      stt: str
      diarize: str
      speaker_embed: str
      llm: str
      text_embed: str


  class AccelerationStatusSchema(BaseModel):
      hardware: HardwareStatusSchema
      plan: PlanSummarySchema
  ```

- [ ] **Step 3 (GREEN): `apps/api/main.py` の lifespan で probe→planner→factory を実行し ctx に格納**
  ```python
  from core.accel.factory import BackendFactory
  from core.accel.plan import UserOverride
  from core.accel.planner import BackendPlanner, plan_to_log_dict
  from core.accel.probe import HardwareProbe

  # lifespan 内で(既存 ctx 構築直後に):
  hw_profile = HardwareProbe().run()
  overrides = UserOverride(
      stt=config.audio.transcriber_backend,
      diarize=config.audio.diarizer_backend,
      speaker_embed=config.audio.speaker_embed_backend,
      llm=config.ollama.runtime_backend,
      text_embed=config.ollama.text_embed_backend,
  )
  plan = BackendPlanner().plan(hw_profile, overrides)
  log.info("acceleration_plan", **plan_to_log_dict(plan))
  ctx.hw_profile = hw_profile
  ctx.backend_plan = plan
  # 注: Phase 1 では既存の ctx.transcriber 等の構築コードは触らない。
  # BackendFactory().build(plan, ...) の置き換えは Phase 2 で実バックエンドが
  # 揃ってから(現状の挙動を変える理由がない)。代わりに、Plan が CUDA を選んで
  # いることだけログで担保する。
  ```
  **Phase 1 設計判断**: `BackendFactory().build()` の結果で `ctx.transcriber` を置換するのは **意図的に Phase 2 へ持ち越す**。理由: Phase 1 で置換しても挙動は不変(CUDA → CUDA)で、リファクタコストとリスクが見合わない。代わりに `ctx.hw_profile` と `ctx.backend_plan` だけを格納し、`GET /api/settings/acceleration` を介して **診断情報** だけを提供する。Phase 2 で実バックエンドが揃ったとき、同 lifespan で `built = BackendFactory().build(plan, config=config); ctx.transcriber = built.transcriber; ...` を追加するだけで済む。

- [ ] **Step 4 (GREEN): `apps/api/routers/settings.py` に `GET /api/settings/acceleration`(read-only)を追加**
  ```python
  @router.get("/settings/acceleration", response_model=AccelerationStatusSchema)
  async def get_acceleration(request: Request) -> AccelerationStatusSchema:
      ctx = request.app.state.ctx
      hw = ctx.hw_profile
      plan = ctx.backend_plan
      return AccelerationStatusSchema(
          hardware=HardwareStatusSchema(
              cpu_brand=hw.cpu_brand,
              dgpu=hw.dgpu, igpu=hw.igpu, npu=hw.npu,
              openvino_devices=list(hw.openvino_devices),
              has_directml=hw.has_directml,
              has_cuda=hw.has_cuda,
              cuda_device_count=hw.cuda_device_count,
              ryzen_ai_gen=hw.ryzen_ai_gen,
          ),
          plan=PlanSummarySchema(
              stt=plan.stt.id, diarize=plan.diarize.id,
              speaker_embed=plan.speaker_embed.id,
              llm=plan.llm.id, text_embed=plan.text_embed.id,
          ),
      )
  ```

- [ ] **Step 5: 緑確認**
  ```
  uv run pytest tests/integration/test_api/test_settings_acceleration.py -v
  ```

- [ ] **Step 6 (AC-CUDA-REGRESSION 実機回帰): 開発機で起動 → エンドポイント確認 → CUDA gate**
  ```
  uv run --extra recording uvicorn apps.api.main:app --port 8765
  # 別ターミナル:
  curl http://localhost:8765/api/settings/acceleration | jq
  ```
  Expected: `plan.stt = "faster-whisper-cuda"`, `plan.llm = "ollama-cuda"`, `hardware.has_cuda = true`。
  さらに:
  ```
  uv run pytest -m "cuda and slow" tests/perf/test_cuda_regression.py -v
  ```
  Expected: PASS(baseline × 1.10 以内)。

- [ ] **Step 7: コミット**
  ```
  git add apps/api/main.py apps/api/dependencies.py apps/api/routers/settings.py apps/api/schemas/settings.py tests/integration/test_api/test_settings_acceleration.py
  git commit -m "feat(api): wire HardwareProbe/Planner into lifespan + GET /settings/acceleration (read-only)"
  ```

### Task 3.5: フロント read-only Acceleration タブ + Playwright 視覚検証

**重要**: ユーザ決定「Settings UI in Phase 1: read-only Acceleration tab showing detected HW + chosen plan, NO override knobs yet」。`<select>` も `[Apply]` も置かない。診断表示だけ。

- [ ] **Step 1**: `apps/web/src/lib/api/types.ts` に型追加
  ```ts
  export interface HardwareStatus {
    cpu_brand: string;
    dgpu: string | null;
    igpu: string | null;
    npu: string | null;
    openvino_devices: string[];
    has_directml: boolean;
    has_cuda: boolean;
    cuda_device_count: number;
    ryzen_ai_gen: number | null;
  }
  export interface PlanSummary {
    stt: string;
    diarize: string;
    speaker_embed: string;
    llm: string;
    text_embed: string;
  }
  export interface AccelerationStatus {
    hardware: HardwareStatus;
    plan: PlanSummary;
  }
  ```

- [ ] **Step 2**: `apps/web/src/lib/api/settings.ts` に `getAcceleration()` だけ追加(`putAcceleration` は Phase 2 のため追加しない)。

- [ ] **Step 3**: `apps/web/src/lib/stores/settings.svelte.ts` に `accelerationStatus: AccelerationStatus | null` + `loadAcceleration()` を追加。

- [ ] **Step 4**: `apps/web/src/lib/components/AccelerationPanel.svelte` を **read-only** で実装
  - Hardware セクション: `Detected GPU/iGPU/NPU/CPU` の 4 行表示。`(none)` を null 時に表示。
  - Backend Plan セクション: 5 行(STT / Diarize / Speaker Embed / LLM / Text Embed)を `<dl>` か `<table>` で **テキスト表示のみ**。
  - **読み込みボタンは [Re-detect] を 1 個だけ置く**(`loadAcceleration()` 再呼び出し)。`<select>` も `[Apply]` も置かない。
  - 「Phase 1 では表示のみ。バックエンド手動上書きは Phase 2 で提供予定」の説明文を冒頭にカード形式で表示。

- [ ] **Step 5**: `apps/web/src/routes/settings/+page.svelte` の左ナビと switch に `acceleration` セクションを追加。

- [ ] **Step 6**: 型/ビルド健全性
  ```
  cd apps/web && npm run check && npm run build
  git checkout -- apps/web/dist/.gitkeep
  ```

- [ ] **Step 7 (視覚検証ゲート — ユーザ規約により必須)**: Playwright MCP で実機スクショ
  ```
  uv run --extra recording uvicorn apps.api.main:app --port 8765
  cd apps/web && npm run dev
  ```
  1. `http://localhost:5173/settings` を navigate、左ナビ「Acceleration」をクリック。
  2. `browser_snapshot` + `browser_take_screenshot` で確認:
     - Hardware セクションに `GPU: NVIDIA CUDA dGPU` / `iGPU: (none)` / `NPU: (none)` / `CPU: 12th Gen Intel ...` が表示される。
     - Backend Plan セクションに `STT: faster-whisper-cuda` / `Diarize: sherpa-onnx-cpu` / `Speaker Embed: sherpa-onnx-cpu` / `LLM: ollama-cuda` / `Text Embed: ollama-bge-m3-cpu` が表示される。
     - 「Phase 1 では表示のみ」の説明カードが表示されている。
     - `<select>` や `[Apply]` ボタンが **存在しない**(`browser_snapshot` のアクセシビリティツリーで確認)。
  3. `[Re-detect]` をクリックし、API 再呼び出しが走り Hardware 表示が維持される(値は同じ)ことを確認。
  4. `browser_console_messages` で console.error が 0 件であることを確認。
  5. NG 時は self-fix(最大 3 回)。

- [ ] **Step 8**: スクショを `docs/screenshots/2026-06-29-acceleration-tab-readonly-cuda.png` で保管しコミット
  ```
  git add apps/web/src tests/integration/test_api/test_settings_acceleration.py docs/screenshots/2026-06-29-acceleration-tab-readonly-cuda.png
  git commit -m "feat(web): add read-only Acceleration settings tab (HW + plan diagnostic)"
  ```

### Sprint 3 受入条件

- [ ] `uv run pytest tests/ -v --ignore=tests/perf` 全 PASS(`runtime` マーカーは除外、perf は別 gate)。
- [ ] `uv run pytest -m "cuda and slow" tests/perf/test_cuda_regression.py -v` PASS(AC-CUDA-REGRESSION 数値ゲート)。
- [ ] 開発機実機で `GET /api/settings/acceleration` が `plan.stt="faster-whisper-cuda"` / `plan.llm="ollama-cuda"` / `hardware.has_cuda=true` を返す。
- [ ] `cd apps/web && npm run check && npm run build` 全 PASS、`apps/web/dist/.gitkeep` が消えていない。
- [ ] Playwright スクショで Acceleration タブが正しく描画され、`<select>` と `[Apply]` が **存在しない**(read-only であること)ことを目視確認したスクショが添付済み。
- [ ] console.error が 0 件(Playwright チェック)。
- [ ] `settings.json` に新フィールドが書かれていない既存ユーザでも起動エラーなし(後方互換、`test_existing_settings_json_without_new_fields_still_loads` で担保)。
- [ ] AC-CUDA-REGRESSION: ライブ字幕 30 秒回しで RTF 維持を **数値ゲート** で確認(baseline × 1.10 以内)。
- [ ] C2 fix: `core/recording/whisper_postprocess.py` が存在し、`grep -nE "HALLUCINATION_NORM|is_voice|apply_rms_floor" core/recording/transcriber.py` の結果が、import 文だけになっている(関数本体は whisper_postprocess に移動済み)。

---

## 全 Sprint 共通の完了確認(Phase 1)

- [ ] `uv run pytest tests/ -v --ignore=tests/perf` 全 PASS(`runtime` マーカーは pytest 設定で除外済み)。
- [ ] `uv run pytest -m "cuda and slow"` の数値リグレッションが green(RTF ≤ baseline × 1.10)。
- [ ] AC-CPU-FALLBACK: `UserOverride(stt="faster-whisper-cpu", llm="ollama-cuda", text_embed="ollama-bge-m3-cpu")` を強制した状態で起動 → ライブ字幕が遅くても動く(目視)。
- [ ] 既存 NVIDIA RTX 2080 Ti ユーザに完全動作回帰なし(数値ゲート + ライブ字幕 30 秒目視 + diarization 結果一致)。
- [ ] Phase 2 deferred セクション(本書末尾)に「未着手の理由・着手前提条件・移行戦略」が記載済み。
- [ ] PR タイトル例: `feat(accel): Phase 1 — HardwareProbe + BackendPlanner + DI skeleton + read-only Acceleration tab`
- [ ] PR 本文に以下を明記:
  - Phase 1 のみの実装で、Phase 2(Intel/AMD 実バックエンド)は別 PR で送る予定
  - 開発機が NVIDIA RTX 2080 Ti のみで Intel iGPU/NPU・AMD Ryzen AI 調達予定なし → Phase 2 は事実上無期限延期
  - `amd-whispercpp-npu` は v1 から削除済み(AMD ユーザは Phase 2 で DirectML 経路のみ)
  - sherpa-onnx は v1+v2 共に CPU 固定(既知制約として `docs/testing/igpu-npu-acceptance.md` に記載)

---

## Phase 2 (deferred)

**ステータス**: 着手見送り(無期限延期)。理由: 開発機が NVIDIA RTX 2080 Ti のみで、Intel iGPU/NPU(Core Ultra)および AMD Ryzen AI ハードウェアの所有・調達予定がない。実機検証が不可能な状態で投機的に Intel/AMD バックエンドを実装してもデッドコードを増やすだけ。

**着手前提条件**:

1. Intel Core Ultra(Lunar Lake / Arrow Lake)または AMD Ryzen AI(Strix / Strix Halo / Krackan Point)実機の入手 — 自前購入 / 借用 / 外部テスタ協力のいずれか
2. Phase 1 が main にマージ済みで CUDA 数値ゲートが安定運用されていること
3. IPEX-LLM が archive されたままなら、OpenVINO GenAI ベースの代替設計を再検討(spec §10 R1 参照)

**Phase 2 で追加する Sprint(原案)**:

- **Sprint 4(Phase 2): Transcriber Protocol 化 + OpenVINO STT バックエンド**
  - `core/recording/transcriber.py` の既存 `Transcriber` を `FasterWhisperTranscriber` にリネーム、`Transcriber` を `runtime_checkable Protocol` として再定義。
  - `core/accel/backends/openvino_whisper.py`(`OpenVINOWhisperTranscriber`、`device="GPU"|"NPU"`)を新規追加。**C2 fix の恩恵**: 幻覚抑制 / RMS floor / VAD ロジックは Phase 1 で抽出済みの `core/recording/whisper_postprocess.py` を import するだけで自動継承される。
  - `BackendFactory._build_transcriber` に分岐追加。`NotImplementedError` を解除。
  - **AMD NPU 用 `amd-whispercpp-npu` は実装しない**(ユーザ決定 3 により v1 から永久削除)。AMD ユーザは Phase 2 でも `faster-whisper-cpu` のまま。

- **Sprint 5(削除): sherpa-onnx provider 切替**
  - ユーザ決定 4 により **完全に削除**。Phase 1+2 とも sherpa-onnx は CPU 固定。本 Sprint は実施しない。`docs/testing/igpu-npu-acceptance.md` に既知制約として明記済み。

- **Sprint 6(Phase 2): TextEmbedder Protocol + OpenVINOTextEmbedder + IPEX-LLM Ollama Portable 子プロセス起動**
  - `core/accel/text_embedder.py`(`TextEmbedder` Protocol + `OpenVINOTextEmbedder`)。
  - `core/accel/runtime_supervisor.py`(`RuntimeSupervisor.ensure_started(plan)` で IPEX-LLM Ollama Portable Zip の `ollama.exe` を `subprocess.Popen`)。
  - `BackendFactory._build_text_embedder` / `_build_ollama_gateway` の Phase 2 ID 分岐を実装(現在の `NotImplementedError` を解除)。
  - `apps/api/main.py` lifespan で `RuntimeSupervisor.shutdown()` を呼ぶ。

- **Sprint 7(Phase 2): Acceleration タブの override UI 追加 + インストールスクリプト + 実機検証手順書完成**
  - `apps/web/src/lib/components/AccelerationPanel.svelte` に `<select>` ドロップダウン(`Mode: Auto/Manual`)・`[Test backends]`・`[Apply]` を追加。
  - `PUT /api/settings/acceleration` を実装(`UserOverride` を `settings.json` に永続化、`BackendFactory.rebuild_in_place(ctx, plan, cfg)` で ctx 内バックエンドを置換)。
  - `scripts/install-intel-runtimes.ps1`(`uv sync --extra intel` + IPEX-LLM Ollama Portable Zip 取得 + 展開)。
  - `scripts/install-amd-runtimes.ps1`(`uv sync --extra amd` + DirectML 経路。**amd whisper.cpp バイナリは取得しない** — v1 から削除)。
  - `docs/testing/igpu-npu-acceptance.md` の完成版(各 AC の実行コマンド + 期待スクショ)。
  - `pyproject.toml` の `intel` / `amd` extras を **空** から実パッケージリストに充填。

**Phase 2 に持ち越す既知制約**:

- 話者分離 / 話者声紋 embedding(sherpa-onnx)は全環境 CPU 固定(ユーザ決定 4)
- AMD Ryzen AI NPU 用 Whisper は実装しない。AMD ユーザは DirectML 経路のみ(ユーザ決定 3)
