# Sprint 1 Smoke Evaluation Report — igpu-npu-accel

## 判定: PASS
## 実行日時: 2026-06-30 (UTC: 2026-06-29T15:14–15:17Z)
## 対象ブランチ: feat/igpu-npu-accel  + stash@{0} "wip: igpu-npu-accel" を適用
## Backend PID (uvicorn): python.exe 33552 (127.0.0.1:8765)

## 証拠ファイル一覧 (絶対パス)
- E:\00_Git\10_NotebookOllama\docs\eval\2026-06-30-igpu-npu-accel-sprint1\ss1-home.png
- E:\00_Git\10_NotebookOllama\docs\eval\2026-06-30-igpu-npu-accel-sprint1\ss2-settings.png
- E:\00_Git\10_NotebookOllama\docs\eval\2026-06-30-igpu-npu-accel-sprint1\ss5-notebook-detail.png
- E:\00_Git\10_NotebookOllama\docs\eval\2026-06-30-igpu-npu-accel-sprint1\console.log
- E:\00_Git\10_NotebookOllama\docs\eval\2026-06-30-igpu-npu-accel-sprint1\network.log
- E:\00_Git\10_NotebookOllama\docs\eval\2026-06-30-igpu-npu-accel-sprint1\smoke-report.md

## Sprint 1 変更の事前確認
- 作業ツリーに以下が存在 (stash@{0} を apply 後):
  - core/accel/{__init__.py, cuda_dll.py, probe.py, probe_cuda.py, probe_env.py, profile.py}
  - core/recording/transcriber.py — `_register_cuda_dll_dirs` をインライン定義から `from core.accel.cuda_dll import _register_cuda_dll_dirs` re-export に変更 (backward compat 維持)
  - pyproject.toml — `cuda` / `slow` pytest マーカーを追加
- バックエンド単体での識別子チェック:
  ```
  uv run python -c "from core.recording.transcriber import _register_cuda_dll_dirs; ..."
  → OK re-export identity: core.accel.cuda_dll
  ```
  → `transcriber._register_cuda_dll_dirs is accel.cuda_dll._register_cuda_dll_dirs` (同じ関数オブジェクト)、`__module__='core.accel.cuda_dll'`。後方互換 import が成立。

## 受入条件別の判定

### SS1: App boots, home page renders — PASS
- URL: http://127.0.0.1:8765/
- ノートブック一覧 (E2E Test Notebook ×2 / 加藤純一 / QSPI / 雑談 / mute-e2e-verify3 ...) が描画。
- ヘッダの「Notebook Ollama」「設定」リンク表示。
- 証拠: ss1-home.png, console.log (errors=0)

### SS2: Settings page loads, 各セクション切替 — PASS
- URL: http://127.0.0.1:8765/settings
- 左ナビ: モデル・Ollama / 生成・検索 / プロンプト / 音声・録音 / ストレージ / 利用可能モデル の 6 セクションを順次クリック、すべて遷移エラーなし。
- **音声・録音 (transcriber.py の下流) を重点確認**:
  - 入力デバイス: マイク既定 / システム音(Loopback) 既定 がプリセット、25 デバイス検出
  - Whisper モデル: large-v3 選択中
  - 実行デバイス: **CUDA** 選択中 (Sprint 1 の CUDA-only baseline)
  - compute_type: float16 選択中
  - 話者分離 / 横断命名 / AGC / 録音音声保持 すべて switch=checked で復元
  - 保存形式 AAC (.m4a) / 64 kbps
- 「クラッシュレポート」セクションは現在のブランチに存在しない (feat/crash-report-feedback-hub 側の機能で未マージ)。Sprint 1 とは独立。
- 証拠: ss2-settings.png (full page), console.log

### SS3: Crash-report regression — SKIP (not applicable on this branch)
- 理由: `/api/settings/crash-report` → **HTTP 404**、`git ls-files | grep -i crash` → 0 件。
- crash-report 機能は `feat/crash-report-feedback-hub` ブランチ (未マージ) にしか存在しない。`feat/igpu-npu-accel` には未到達なので Sprint 1 の影響範囲外。
- 結論: Sprint 1 リファクタの regression ではなく、機能そのものが存在しない → SKIP。

### SS4: Drawer / Megaphone — SKIP (not applicable on this branch)
- 理由: ホーム画面の DOM スナップショットおよび `aria-label` 検索 (`/megaphone|フィードバック|drawer|feedback/i`) で 0 件。`git ls-files | grep -iE "megaphone|drawer|feedback"` も 0 件。
- 同じく `feat/crash-report-feedback-hub` 由来の機能で本ブランチには未到達。SKIP。

### SS5: Transcriber import path (critical backend smoke) — PASS
- `curl http://127.0.0.1:8765/api/notebooks` → **HTTP 200**, 3203 bytes JSON。`apps.api.main → core.* → core.recording.transcriber → core.accel.cuda_dll` の import 連鎖が壊れていない実証。
- ブラウザで `/notebooks/01KW711X3EPBBBXYMWAH4PF5JG` 遷移、「加藤純一」タイトルと録音/ライブ字幕系の UI 文言がレンダリング (`hasRecording=true`, `hasNotebookTitle=true`)。
- 追加 API: `/api/notebooks/:id` 200, `/api/notebooks/:id/sources` 200, `/api/models` 200, `/api/settings` 200, `/api/stats` 200, `/api/prompts` 200。
- バックエンド単体 import チェック (上述) も成功。
- 証拠: ss5-notebook-detail.png, network.log, console.log

### SS6: Console errors check — PASS
- 全シナリオ通算: `Total messages: 0 (Errors: 0, Warnings: 0)`
- accel / recording / transcriber に関する RED ログ: 0 件。

## console.error 件数: 0
## network 失敗件数: 0 (記録された API 呼び出しはすべて 200)

## verdict 根拠
- 実行可能シナリオ (SS1 / SS2 / SS5 / SS6) はすべて PASS。
- SS3 / SS4 は対象機能が本ブランチに存在しない → SKIP (Sprint 1 リファクタの責に帰さない)。
- console.error = 0、API 失敗 = 0。
- Sprint 1 の唯一のプロダクション影響変更 (`transcriber.py` の `_register_cuda_dll_dirs` re-export) は、本番 import チェイン (uvicorn boot → /api/notebooks 200) と単体 import チェイン (`uv run python -c ...`) の両方で正常動作を確認。

## 推定原因 (FAIL の場合)
N/A — verdict=PASS。

## 制限事項 (Generator/Orchestrator への申し送り)
1. Sprint 1 の差分は依然 stash@{0} 上にあり、未コミット。Generator が commit/push する前段階を Evaluator が観測した形。コミット後の状態でもう一度同じ smoke が必要なら再実行 (差分が同一なら結果は同一の見込み)。
2. feat/igpu-npu-accel には `feat/crash-report-feedback-hub` 由来の機能 (crash-report / Megaphone drawer) が未マージで、SS3/SS4 は元の指示通りには実行不能。crash-report の regression を見たい場合は別途 `feat/crash-report-feedback-hub` を取り込んだ統合ブランチで再評価が必要。
3. 今回は backend-only リファクタの smoke のため、GPU 実機での CUDA 推論 (large-v3 + float16) や `_register_cuda_dll_dirs` の add_dll_directory 効果までは検証していない (Playwright 検証の範囲外)。CUDA 動作確認は Sprint 2 以降の probe テスト (tests/integration/test_accel/) で別途カバーされる想定。
