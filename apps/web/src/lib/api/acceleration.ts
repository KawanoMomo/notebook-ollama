import { request } from './client';

/**
 * Sprint 3 / Task 3.5 — Acceleration tab read-only API.
 *
 * Mirrors the wire format returned by ``GET /api/settings/acceleration``
 * (see ``apps/api/schemas/settings.py::AccelerationResponseSchema``). The
 * Phase 1 endpoint is read-only; per-role backend overrides land in Phase 2.
 */

export interface HwProfile {
  /** Marketing-name CPU brand string, e.g. "12th Gen Intel(R) Core(TM) i9-12900KF". */
  cpu_brand: string;
  /** True iff faster-whisper / Ollama can see at least one CUDA dGPU. */
  cuda: boolean;
  /** NVIDIA dGPU name reported by nvidia-smi, or null. */
  dgpu: string | null;
  /** Coarse Intel iGPU label ("Intel iGPU") or null. AMD iGPUs not detected in Phase 1. */
  igpu: string | null;
  /** Friendly NPU label ("Intel NPU" / "phoenix" / "hawk_point" / ...) or null. */
  npu: string | null;
  /** dGPU VRAM in MiB. Null when no dGPU. */
  vram_mb: number | null;
  /** XDNA generation for AMD NPUs (1 = Phoenix/HawkPoint, 2 = Strix/KrackanPoint). */
  ryzen_ai_gen: number | null;
  /** OpenVINO device names exposed by the wheel ("CPU" | "GPU" | "NPU"). */
  openvino_devices: string[];
  /** True iff onnxruntime exposes DmlExecutionProvider. */
  has_directml: boolean;
}

export interface BackendPlan {
  /** STT backend id (e.g. "faster-whisper-cuda" / "faster-whisper-cpu"). */
  stt_id: string;
  /** Diarization backend id — always "sherpa-onnx-cpu" in v1+v2. */
  diarize_id: string;
  /** LLM backend id ("ollama-cuda" covers CPU-only too via auto-degrade). */
  llm_id: string;
  /** Text embedding backend id. */
  text_embed_id: string;
  /** Human-readable explanation of every per-role decision. */
  reason: string;
}

export interface AccelerationResponse {
  hw_profile: HwProfile;
  backend_plan: BackendPlan;
  /** False when the Planner picked a Phase 2 backend id the Factory can't yet build. */
  is_phase1_implementable: boolean;
}

export const accelerationApi = {
  get: () => request<AccelerationResponse>('/api/settings/acceleration'),
};
