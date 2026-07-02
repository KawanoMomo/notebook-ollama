<script lang="ts">
  /**
   * Sprint 3 / Task 3.5 — Acceleration tab (READ-ONLY in Phase 1).
   *
   * Display sections:
   *   1. 検出ハードウェア — CPU / CUDA dGPU / Intel iGPU+NPU / AMD NPU / DirectML
   *   2. 選択されたバックエンド — STT / Diarize / LLM / Text Embed (id + reason)
   *   3. Phase 1 実装可能 — badge
   *   4. [再検出] button — re-issues GET /api/settings/acceleration
   *   5. Phase 1 説明 card (gray bg) — "Intel iGPU/NPU と AMD Ryzen AI は Phase 2 で実装予定"
   *
   * Per spec: NO <select> override, NO [Apply] button — backend selection
   * via UI lands in Phase 2.
   */
  import { onMount } from 'svelte';
  import {
    accelerationApi as defaultApi,
    type AccelerationResponse,
  } from '$lib/api/acceleration';

  type Props = {
    api?: typeof defaultApi;
  };
  let { api = defaultApi }: Props = $props();

  let data = $state<AccelerationResponse | null>(null);
  let loading = $state(false);
  let error = $state<string | null>(null);

  async function load() {
    loading = true;
    error = null;
    try {
      data = await api.get();
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    } finally {
      loading = false;
    }
  }

  onMount(load);
</script>

<h3>アクセラレーション</h3>
<p class="sub">
  起動時に検出されたハードウェアと、そこから自動選択された各バックエンドを表示します。
  Phase 1 では設定変更不可(再起動で再検出)。
</p>

{#if loading && data === null}
  <div class="loading">読み込み中…</div>
{:else if error}
  <div class="loading err">アクセラレーション情報の取得に失敗しました: {error}</div>
{:else if data}
  <!-- 1. 検出ハードウェア -->
  <div class="group">
    <p class="gh">検出ハードウェア</p>
    <div class="row">
      <div class="lab">CPU</div>
      <div class="ctl"><span class="mono">{data.hw_profile.cpu_brand}</span></div>
    </div>

    {#if data.hw_profile.cuda && data.hw_profile.dgpu}
      <div class="row">
        <div class="lab">CUDA dGPU<small>NVIDIA GPU</small></div>
        <div class="ctl">
          <span class="badge ok">CUDA</span>
          <span class="mono">{data.hw_profile.dgpu}</span>
          {#if data.hw_profile.vram_mb !== null}
            <span class="hint-text">VRAM {data.hw_profile.vram_mb} MiB</span>
          {/if}
        </div>
      </div>
    {/if}

    {#if data.hw_profile.openvino_devices.length > 0 || data.hw_profile.igpu}
      <div class="row">
        <div class="lab">Intel iGPU / NPU<small>OpenVINO 経由(Phase 2)</small></div>
        <div class="ctl">
          {#if data.hw_profile.igpu}
            <span class="badge accent">{data.hw_profile.igpu}</span>
          {/if}
          {#if data.hw_profile.npu && data.hw_profile.npu.toLowerCase().includes('intel')}
            <span class="badge accent">{data.hw_profile.npu}</span>
          {/if}
          {#if data.hw_profile.openvino_devices.length > 0}
            <span class="hint-text">
              OpenVINO: {data.hw_profile.openvino_devices.join(', ')}
            </span>
          {/if}
        </div>
      </div>
    {/if}

    {#if data.hw_profile.ryzen_ai_gen !== null}
      <div class="row">
        <div class="lab">AMD Ryzen AI / NPU<small>Phase 2</small></div>
        <div class="ctl">
          {#if data.hw_profile.npu}
            <span class="badge accent">{data.hw_profile.npu}</span>
          {/if}
          <span class="hint-text">XDNA 世代: {data.hw_profile.ryzen_ai_gen}</span>
        </div>
      </div>
    {/if}

    <div class="row">
      <div class="lab">DirectML<small>onnxruntime DmlExecutionProvider</small></div>
      <div class="ctl">
        {#if data.hw_profile.has_directml}
          <span class="badge ok">利用可能</span>
          <span class="hint-text">DirectML 検出</span>
        {:else}
          <span class="badge muted">未検出</span>
          <span class="hint-text">DirectML は利用できません</span>
        {/if}
      </div>
    </div>
  </div>

  <!-- 2. 選択されたバックエンド -->
  <div class="group">
    <p class="gh">選択されたバックエンド</p>
    <div class="row">
      <div class="lab">STT(文字起こし)</div>
      <div class="ctl"><code>{data.backend_plan.stt_id}</code></div>
    </div>
    <div class="row">
      <div class="lab">Diarize(話者分離)</div>
      <div class="ctl"><code>{data.backend_plan.diarize_id}</code></div>
    </div>
    <div class="row">
      <div class="lab">LLM(生成)</div>
      <div class="ctl"><code>{data.backend_plan.llm_id}</code></div>
    </div>
    <div class="row">
      <div class="lab">Text Embed(埋め込み)</div>
      <div class="ctl"><code>{data.backend_plan.text_embed_id}</code></div>
    </div>
    <div class="row">
      <div class="lab">選定理由</div>
      <div class="ctl"><span class="reason">{data.backend_plan.reason}</span></div>
    </div>
  </div>

  <!-- 3. Phase 1 実装可能 badge + 4. Re-detect -->
  <div class="group">
    <p class="gh">状態</p>
    <div class="row">
      <div class="lab">Phase 1 実装可能</div>
      <div class="ctl">
        {#if data.is_phase1_implementable}
          <span class="badge ok">Phase 1 実装可能 ✓</span>
        {:else}
          <span class="badge warn">Phase 1 未実装(CPU 代替で動作中)</span>
        {/if}
      </div>
    </div>
    <div class="row">
      <div class="lab">再検出</div>
      <div class="ctl">
        <button
          class="btn"
          onclick={load}
          disabled={loading}
          aria-label="再検出"
        >
          {loading ? '再検出中…' : '↻ 再検出'}
        </button>
        <span class="hint-text">フル再プローブはアプリ再起動が必要です</span>
      </div>
    </div>
  </div>

  <!-- 5. Phase 1 説明 card -->
  <div class="hintbox phase-note">
    <strong>Phase 1 の制限</strong><br />
    Intel iGPU/NPU および AMD Ryzen AI 対応は Phase 2 で実装予定です。
    現在は NVIDIA CUDA と CPU のみが動作します。
  </div>
{/if}

<style>
  h3 {
    margin: 0 0 var(--space-1);
    font-size: 17px;
  }
  .sub {
    color: var(--color-fg-muted);
    font-size: 12px;
    margin: 0 0 var(--space-5);
  }

  .loading {
    padding: var(--space-5);
    color: var(--color-fg-muted);
    text-align: center;
  }
  .loading.err {
    color: var(--color-error);
  }

  .group {
    margin-bottom: 22px;
  }
  .gh {
    font-size: 12px;
    color: var(--color-fg-muted);
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin: 0 0 10px;
    border-bottom: 1px solid var(--color-border);
    padding-bottom: 6px;
  }

  .row {
    display: grid;
    grid-template-columns: 230px 1fr;
    gap: 10px 18px;
    align-items: center;
    padding: 9px 0;
  }
  .row + .row {
    border-top: 1px solid #f0f0f2;
  }

  .lab {
    font-size: 13px;
  }
  .lab small {
    display: block;
    color: var(--color-fg-muted);
    font-size: 11px;
    margin-top: 2px;
    font-weight: 400;
  }

  .ctl {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    flex-wrap: wrap;
  }

  .mono {
    font-family: var(--font-mono);
    font-size: 12px;
  }

  code {
    font-family: var(--font-mono);
    font-size: 12px;
    background: var(--color-bg-elevated);
    padding: 1px var(--space-2);
    border-radius: var(--radius-sm);
  }

  .reason {
    font-size: 12px;
    color: var(--color-fg-muted);
    line-height: 1.6;
  }

  .badge {
    font-size: 11px;
    border-radius: 999px;
    padding: 2px var(--space-2);
    font-weight: 600;
  }
  .badge.ok {
    background: #e7f5e8;
    color: var(--color-success);
  }
  .badge.warn {
    background: #fff4e5;
    color: #8a5300;
  }
  .badge.accent {
    background: var(--color-bg-elevated);
    color: var(--color-accent);
  }
  .badge.muted {
    background: var(--color-bg-elevated);
    color: var(--color-fg-muted);
  }

  .hint-text {
    font-size: 11px;
    color: var(--color-fg-muted);
  }

  .btn {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    border: 1px solid var(--color-border);
    background: var(--color-bg);
    color: var(--color-fg);
    border-radius: var(--radius-md);
    padding: 6px 11px;
    font-size: 12px;
    font-weight: 500;
    cursor: pointer;
  }
  .btn:disabled {
    opacity: 0.6;
    cursor: not-allowed;
  }

  .hintbox {
    background: var(--color-bg-elevated);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    padding: 10px 12px;
    font-size: 12px;
    color: var(--color-fg-muted);
    line-height: 1.7;
    margin-top: var(--space-2);
  }
  .phase-note {
    background: #f5f5f7;
  }
</style>
