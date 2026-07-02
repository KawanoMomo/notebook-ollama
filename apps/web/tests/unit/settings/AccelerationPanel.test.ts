/**
 * Sprint 3 / Task 3.5 — AccelerationPanel.svelte unit tests.
 *
 * Phase 1 contract:
 *
 * - Render the resolved HwProfile + BackendPlan sections.
 * - READ-ONLY: no <select> element, no [Apply] button.
 * - [再検出] button is visible (re-issues GET /api/settings/acceleration).
 * - Phase 1 explanation card is visible.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import AccelerationPanel from '$lib/components/settings/AccelerationPanel.svelte';
import type { AccelerationResponse } from '$lib/api/acceleration';

afterEach(() => cleanup());

function makeResponse(over: Partial<AccelerationResponse> = {}): AccelerationResponse {
  return {
    hw_profile: {
      cpu_brand: '12th Gen Intel(R) Core(TM) i9-12900KF',
      cuda: true,
      dgpu: 'NVIDIA GeForce RTX 2080 Ti',
      igpu: null,
      npu: null,
      vram_mb: 11264,
      ryzen_ai_gen: null,
      openvino_devices: [],
      has_directml: false,
    },
    backend_plan: {
      stt_id: 'faster-whisper-cuda',
      diarize_id: 'sherpa-onnx-cpu',
      llm_id: 'ollama-cuda',
      text_embed_id: 'ollama-bge-m3-cpu',
      reason: 'CUDA dGPU detected -> faster-whisper-cuda',
    },
    is_phase1_implementable: true,
    ...over,
  };
}

function makeApi(response: AccelerationResponse) {
  return {
    get: vi.fn().mockResolvedValue(response),
  };
}

describe('AccelerationPanel — hardware section', () => {
  it('shows the CPU brand string', async () => {
    const api = makeApi(makeResponse());
    render(AccelerationPanel, { api });
    await waitFor(() => expect(api.get).toHaveBeenCalled());
    expect(screen.getByText(/i9-12900KF/)).toBeDefined();
  });

  it('shows the CUDA dGPU name + VRAM when CUDA is present', async () => {
    const api = makeApi(makeResponse());
    render(AccelerationPanel, { api });
    await waitFor(() => expect(api.get).toHaveBeenCalled());
    expect(screen.getByText(/RTX 2080 Ti/)).toBeDefined();
    // VRAM rendered (some unit suffix — MB / MiB acceptable)
    expect(screen.getByText(/11264/)).toBeDefined();
  });

  it('shows the Intel iGPU + NPU sections when OpenVINO devices are present', async () => {
    const api = makeApi(
      makeResponse({
        hw_profile: {
          cpu_brand: 'Intel(R) Core(TM) Ultra 7 155H',
          cuda: false,
          dgpu: null,
          igpu: 'Intel iGPU',
          npu: 'Intel NPU',
          vram_mb: null,
          ryzen_ai_gen: null,
          openvino_devices: ['CPU', 'GPU', 'NPU'],
          has_directml: false,
        },
      }),
    );
    render(AccelerationPanel, { api });
    await waitFor(() => expect(api.get).toHaveBeenCalled());
    // 'Intel iGPU' appears as both row label and badge → at least one match.
    expect(screen.getAllByText(/Intel iGPU/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Intel NPU/).length).toBeGreaterThan(0);
    // OpenVINO device list is exposed for the operator.
    expect(screen.getByText(/OpenVINO:.*CPU.*GPU.*NPU/)).toBeDefined();
  });

  it('shows AMD NPU section when ryzen_ai_gen is set', async () => {
    const api = makeApi(
      makeResponse({
        hw_profile: {
          cpu_brand: 'AMD Ryzen AI 9 HX 370',
          cuda: false,
          dgpu: null,
          igpu: null,
          npu: 'strix',
          vram_mb: null,
          ryzen_ai_gen: 2,
          openvino_devices: [],
          has_directml: true,
        },
      }),
    );
    render(AccelerationPanel, { api });
    await waitFor(() => expect(api.get).toHaveBeenCalled());
    expect(screen.getByText(/strix/)).toBeDefined();
  });

  it('shows DirectML availability indicator', async () => {
    const api = makeApi(
      makeResponse({
        hw_profile: {
          ...makeResponse().hw_profile,
          has_directml: true,
        },
      }),
    );
    render(AccelerationPanel, { api });
    await waitFor(() => expect(api.get).toHaveBeenCalled());
    // Label + status text both mention DirectML — assert any element matches.
    expect(screen.getAllByText(/DirectML/i).length).toBeGreaterThan(0);
  });
});

describe('AccelerationPanel — backend plan section', () => {
  it('shows each backend id (STT / Diarize / LLM / Text Embed)', async () => {
    const api = makeApi(makeResponse());
    render(AccelerationPanel, { api });
    await waitFor(() => expect(api.get).toHaveBeenCalled());
    expect(screen.getByText('faster-whisper-cuda')).toBeDefined();
    expect(screen.getByText('sherpa-onnx-cpu')).toBeDefined();
    expect(screen.getByText('ollama-cuda')).toBeDefined();
    expect(screen.getByText('ollama-bge-m3-cpu')).toBeDefined();
  });

  it('shows the plan reason', async () => {
    const api = makeApi(makeResponse());
    render(AccelerationPanel, { api });
    await waitFor(() => expect(api.get).toHaveBeenCalled());
    expect(screen.getByText(/CUDA dGPU detected/)).toBeDefined();
  });
});

describe('AccelerationPanel — Phase 1 gate badge', () => {
  it('shows OK badge when is_phase1_implementable=true', async () => {
    const api = makeApi(makeResponse({ is_phase1_implementable: true }));
    render(AccelerationPanel, { api });
    await waitFor(() => expect(api.get).toHaveBeenCalled());
    // Label + badge both contain the phrase; assert that at least one element
    // carries the OK marker (✓).
    expect(screen.getByText(/Phase 1 実装可能 ✓/)).toBeDefined();
  });

  it('shows fallback badge when is_phase1_implementable=false', async () => {
    const api = makeApi(makeResponse({ is_phase1_implementable: false }));
    render(AccelerationPanel, { api });
    await waitFor(() => expect(api.get).toHaveBeenCalled());
    // CPU 代替で動作中 indicator must appear.
    expect(screen.getByText(/CPU 代替で動作中/)).toBeDefined();
  });
});

describe('AccelerationPanel — read-only contract', () => {
  it('has NO <select> elements (read-only Phase 1)', async () => {
    const api = makeApi(makeResponse());
    const { container } = render(AccelerationPanel, { api });
    await waitFor(() => expect(api.get).toHaveBeenCalled());
    expect(container.querySelectorAll('select').length).toBe(0);
  });

  it('has NO [Apply] / [適用] button (read-only Phase 1)', async () => {
    const api = makeApi(makeResponse());
    render(AccelerationPanel, { api });
    await waitFor(() => expect(api.get).toHaveBeenCalled());
    expect(screen.queryByRole('button', { name: /apply|適用/i })).toBeNull();
  });
});

describe('AccelerationPanel — [Re-detect] button', () => {
  it('renders the [Re-detect] button', async () => {
    const api = makeApi(makeResponse());
    render(AccelerationPanel, { api });
    await waitFor(() => expect(api.get).toHaveBeenCalled());
    expect(screen.getByRole('button', { name: /再検出/ })).toBeDefined();
  });

  it('clicking [Re-detect] re-issues the GET request', async () => {
    const api = makeApi(makeResponse());
    render(AccelerationPanel, { api });
    await waitFor(() => expect(api.get).toHaveBeenCalledTimes(1));
    await fireEvent.click(screen.getByRole('button', { name: /再検出/ }));
    await waitFor(() => expect(api.get).toHaveBeenCalledTimes(2));
  });
});

describe('AccelerationPanel — Phase 1 explanation card', () => {
  it('renders the Phase 2 roadmap notice', async () => {
    const api = makeApi(makeResponse());
    render(AccelerationPanel, { api });
    await waitFor(() => expect(api.get).toHaveBeenCalled());
    expect(screen.getByText(/Intel iGPU\/NPU/)).toBeDefined();
    expect(screen.getByText(/Phase 2/)).toBeDefined();
  });
});
