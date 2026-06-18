<script lang="ts">
  import { onMount } from 'svelte';
  import type { AudioSettings } from '$lib/api/types';
  import { settingsApi } from '$lib/api/settings';
  import { settingsStore } from '$lib/stores/settings.svelte';
  import { recordingsApi, type AudioDevice } from '$lib/api/recordings';
  import { pushToast } from '$lib/components/Toast.svelte';

  // 編集用ローカルコピー。store の値を初期値にする。
  let draft = $state<AudioSettings | null>(null);
  let devices = $state<AudioDevice[]>([]);
  let deviceErr = $state<string | null>(null);
  let saving = $state(false);
  let scanning = $state(false);

  function snapshot(): AudioSettings | null {
    const a = settingsStore.settings?.audio;
    return a ? { ...a } : null;
  }

  async function loadDevices() {
    scanning = true;
    deviceErr = null;
    try {
      devices = await recordingsApi.devices();
    } catch (e) {
      deviceErr = e instanceof Error ? e.message : String(e);
    } finally {
      scanning = false;
    }
  }

  onMount(() => {
    draft = snapshot();
    loadDevices();
  });

  function reset() {
    draft = snapshot();
  }

  async function save() {
    if (!draft) return;
    saving = true;
    try {
      const updated = await settingsApi.putAudio(draft);
      // store 側も更新(再読込でも可)
      await settingsStore.load();
      draft = { ...updated };
      pushToast('音声・録音設定を保存しました', 'success');
    } catch (e) {
      pushToast(e instanceof Error ? e.message : String(e), 'error');
    } finally {
      saving = false;
    }
  }

  const WHISPER_MODELS = ['tiny', 'base', 'small', 'medium', 'large-v3'];
  const COMPUTE_TYPES = ['float16', 'int8_float16', 'int8'];
  const STORAGE_FORMATS: { v: AudioSettings['storage_format']; label: string }[] = [
    { v: 'aac', label: 'AAC (.m4a)' },
    { v: 'opus', label: 'Opus (.opus)' },
    { v: 'mp3', label: 'MP3 (.mp3)' },
    { v: 'wav', label: 'WAV (無圧縮)' },
  ];
  const BITRATES = [32, 48, 64, 96, 128];
</script>

{#if draft === null}
  <div class="loading">読み込み中…</div>
{:else}
  <h3>音声・録音</h3>
  <p class="sub">録音(マイク + システム音)と、停止後の高精度 RAG 変換に関する設定。デバイス選択はここで一括設定し、録音画面には出しません。</p>

  <!-- 入力デバイス -->
  <div class="group">
    <p class="gh">入力デバイス</p>
    <div class="row">
      <div class="lab">マイク<small>あなたの声</small></div>
      <div class="ctl">
        <select bind:value={draft.mic_device_index}>
          <option value={null}>既定マイク</option>
          {#each devices.filter(d => !d.is_loopback) as device (device.index)}
            <option value={device.index}>{device.name}</option>
          {/each}
          {#each devices.filter(d => d.is_loopback) as device (device.index)}
            <option value={device.index}>{device.name}</option>
          {/each}
        </select>
      </div>
    </div>
    <div class="row">
      <div class="lab">システム音(ループバック)<small>相手の声・再生中の音(WASAPI)</small></div>
      <div class="ctl">
        <select bind:value={draft.system_device_index}>
          <option value={null}>既定出力の Loopback</option>
          {#each devices as device (device.index)}
            <option value={device.index}>{device.name}</option>
          {/each}
        </select>
      </div>
    </div>
    <div class="row">
      <div class="lab">デバイス再検出</div>
      <div class="ctl">
        <button class="btn" onclick={loadDevices} disabled={scanning}>↻ 再スキャン</button>
        <span class="badge ok">{devices.length} デバイス検出</span>
        {#if deviceErr}
          <span class="err-text">{deviceErr}</span>
        {/if}
      </div>
    </div>
  </div>

  <!-- 文字起こし(STT) -->
  <div class="group">
    <p class="gh">文字起こし(STT / faster-whisper)</p>
    <div class="row">
      <div class="lab">Whisper モデル<small>大きいほど高精度・低速</small></div>
      <div class="ctl">
        <select bind:value={draft.whisper_model}>
          {#each WHISPER_MODELS as m (m)}
            <option value={m}>{m}</option>
          {/each}
        </select>
      </div>
    </div>
    <div class="row">
      <div class="lab">実行デバイス</div>
      <div class="ctl">
        <select bind:value={draft.device}>
          <option value="cuda">CUDA</option>
          <option value="cpu">CPU</option>
        </select>
      </div>
    </div>
    <div class="row">
      <div class="lab">compute_type</div>
      <div class="ctl">
        <select bind:value={draft.compute_type}>
          {#each COMPUTE_TYPES as ct (ct)}
            <option value={ct}>{ct}</option>
          {/each}
        </select>
      </div>
    </div>
  </div>

  <!-- ライブ字幕 -->
  <div class="group">
    <p class="gh">ライブ字幕(録音中のプレビュー)</p>
    <div class="row">
      <div class="lab">既定で ON<small>サイドバーのトグルの初期値</small></div>
      <div class="ctl">
        <button
          class="switch"
          class:off={!draft.live_caption_default}
          role="switch"
          aria-checked={draft.live_caption_default}
          aria-label="ライブ字幕 既定で ON"
          onclick={() => { if (draft) draft.live_caption_default = !draft.live_caption_default; }}
        ><i></i></button>
      </div>
    </div>
    <div class="row">
      <div class="lab">自動ゲイン(AGC)<small>小さい声を自動で持ち上げる</small></div>
      <div class="ctl">
        <button
          class="switch"
          class:off={!draft.agc_enabled}
          role="switch"
          aria-checked={draft.agc_enabled}
          aria-label="自動ゲイン(AGC)"
          onclick={() => { if (draft) draft.agc_enabled = !draft.agc_enabled; }}
        ><i></i></button>
      </div>
    </div>
  </div>

  <!-- 話者分離 / 名前予想 -->
  <div class="group">
    <p class="gh">話者分離 / 名前予想(停止後の高精度変換)</p>
    <div class="row">
      <div class="lab">話者分離(sherpa-onnx)<small>相手を 相手1 / 相手2 … に分離</small></div>
      <div class="ctl">
        <button
          class="switch"
          class:off={!draft.diarization_enabled}
          role="switch"
          aria-checked={draft.diarization_enabled}
          aria-label="話者分離"
          onclick={() => { if (draft) draft.diarization_enabled = !draft.diarization_enabled; }}
        ><i></i></button>
      </div>
    </div>
    <div class="row">
      <div class="lab">最大話者数</div>
      <div class="ctl">
        <select bind:value={draft.max_speakers}>
          <option value={null}>自動</option>
          {#each [2, 3, 4, 5, 6] as n (n)}
            <option value={n}>{n}</option>
          {/each}
        </select>
      </div>
    </div>
    <div class="row">
      <div class="lab">声紋で横断命名<small>過去に命名した話者を自動一致</small></div>
      <div class="ctl">
        <button
          class="switch"
          class:off={!draft.voiceprint_naming}
          role="switch"
          aria-checked={draft.voiceprint_naming}
          aria-label="声紋で横断命名"
          onclick={() => { if (draft) draft.voiceprint_naming = !draft.voiceprint_naming; }}
        ><i></i></button>
      </div>
    </div>
    <div class="row">
      <div class="lab">LLM 内容推定で名前予想<small>会話内容から話者名を推定(例:「○○さんお願いします」)</small></div>
      <div class="ctl">
        <button
          class="switch"
          class:off={!draft.name_inference_llm}
          role="switch"
          aria-checked={draft.name_inference_llm}
          aria-label="LLM 内容推定で名前予想"
          onclick={() => { if (draft) draft.name_inference_llm = !draft.name_inference_llm; }}
        ><i></i></button>
      </div>
    </div>
    <div class="row">
      <div class="lab">名前採用のしきい値</div>
      <div class="ctl">
        <input
          type="range"
          min="0"
          max="1"
          step="0.05"
          bind:value={draft.name_threshold}
          class="range-input"
        />
        <span class="mono">{draft.name_threshold.toFixed(2)}</span>
        <span class="hint-text">未満は「相手N」のまま</span>
      </div>
    </div>
  </div>

  <!-- 録音データの保存 -->
  <div class="group">
    <p class="gh">録音データの保存</p>
    <div class="row">
      <div class="lab">保存形式(圧縮)<small>録音中・変換中はWAV。完了後にこの形式へ変換しWAVは削除</small></div>
      <div class="ctl">
        <select bind:value={draft.storage_format}>
          {#each STORAGE_FORMATS as fmt (fmt.v)}
            <option value={fmt.v}>{fmt.label}</option>
          {/each}
        </select>
      </div>
    </div>
    <div class="row">
      <div class="lab">ビットレート</div>
      <div class="ctl">
        <select bind:value={draft.storage_bitrate_kbps}>
          {#each BITRATES as n (n)}
            <option value={n}>{n} kbps</option>
          {/each}
        </select>
      </div>
    </div>
    <div class="row">
      <div class="lab">録音音声を保持<small>引用 → 該当箇所の再生に必要。OFFでテキスト引用のみ</small></div>
      <div class="ctl">
        <button
          class="switch"
          class:off={!draft.keep_audio}
          role="switch"
          aria-checked={draft.keep_audio}
          aria-label="録音音声を保持"
          onclick={() => { if (draft) draft.keep_audio = !draft.keep_audio; }}
        ><i></i></button>
      </div>
    </div>
    <div class="hintbox">
      録音は <span class="mono">data/sources/&lt;source_id&gt;/audio.m4a</span> として保存(変換は ffmpeg、WAVは変換後に削除)。リポジトリには含めません。再処理(再起こし)もこの圧縮ファイルから行います。
    </div>
  </div>

  <!-- savebar -->
  <div class="savebar">
    <button class="btn" onclick={reset}>既定に戻す</button>
    <button class="btn primary" onclick={save} disabled={saving}>
      {saving ? '保存中…' : '保存'}
    </button>
  </div>
{/if}

<style>
  .loading {
    padding: var(--space-5);
    color: var(--color-fg-muted);
    text-align: center;
  }

  h3 {
    margin: 0 0 var(--space-1);
    font-size: 17px;
  }

  .sub {
    color: var(--color-fg-muted);
    font-size: 12px;
    margin: 0 0 var(--space-5);
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

  select {
    font: inherit;
    font-size: 13px;
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    padding: 6px 9px;
    background: var(--color-bg);
    min-width: 200px;
  }

  .switch {
    width: 40px;
    height: 23px;
    border-radius: 999px;
    background: var(--color-accent);
    position: relative;
    flex: none;
    border: none;
    padding: 0;
  }

  .switch.off {
    background: #c8c8cd;
  }

  .switch i {
    position: absolute;
    top: 2px;
    width: 19px;
    height: 19px;
    border-radius: 50%;
    background: #fff;
    box-shadow: 0 1px 2px rgba(0, 0, 0, 0.3);
    right: 2px;
    transition: right 0.12s, left 0.12s;
  }

  .switch.off i {
    right: auto;
    left: 2px;
  }

  .range-input {
    width: 160px;
    accent-color: var(--color-accent);
  }

  .mono {
    font-family: var(--font-mono);
    font-size: 12px;
  }

  .hint-text {
    font-size: 11px;
    color: var(--color-fg-muted);
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

  .err-text {
    font-size: 11px;
    color: var(--color-error);
  }

  .hintbox {
    background: var(--color-bg-elevated);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    padding: 10px 12px;
    font-size: 12px;
    color: var(--color-fg-muted);
    line-height: 1.6;
    margin-top: var(--space-2);
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
  }

  .btn:disabled {
    opacity: 0.6;
    cursor: not-allowed;
  }

  .btn.primary {
    background: var(--color-accent);
    border-color: var(--color-accent);
    color: #fff;
  }

  .savebar {
    position: sticky;
    bottom: 0;
    margin-top: 18px;
    padding-top: 14px;
    border-top: 1px solid var(--color-border);
    display: flex;
    justify-content: flex-end;
    gap: var(--space-2);
    background: linear-gradient(transparent, var(--color-bg) 40%);
  }
</style>
