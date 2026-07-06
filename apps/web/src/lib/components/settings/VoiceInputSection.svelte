<script lang="ts">
  import { settingsStore } from '$lib/stores/settings.svelte';
  import { settingsApi } from '$lib/api/settings';
  import { pushToast } from '$lib/components/Toast.svelte';
  import Spinner from '$lib/components/Spinner.svelte';
  import type { VoiceInputMode } from '$lib/api/types';

  let mode = $state<VoiceInputMode>('push_to_talk');
  let pttKey = $state('Space');
  let capturing = $state(false);
  let saving = $state(false);
  let initialized = false;

  // settings は非同期ロード (親 +page.svelte の onMount で settingsStore.load() 済み)
  // のため、本コンポーネントの mount 時点では未到着のことがある。到着し次第
  // mode/pttKey を初回だけ同期する(AudioSettingsSection の `draft === null`
  // ガードと同じ考え方 — 初回限定にすることで、ユーザ編集後に上書きしない)。
  $effect(() => {
    const vi = settingsStore.settings?.voice_input;
    if (vi && !initialized) {
      mode = vi.mode;
      pttKey = vi.ptt_key;
      initialized = true;
    }
  });

  function startCapture() {
    capturing = true;
  }

  function onWindowKeydown(e: KeyboardEvent) {
    if (!capturing) return;
    // キャプチャ開始後にモードラジオで PTT 以外へ切り替えられた場合は
    // キャプチャを解除する(disabled 表示とキャプチャ生存の不整合防止)。
    if (mode !== 'push_to_talk') {
      capturing = false;
      return;
    }
    e.preventDefault();
    if (e.code === 'Escape') {
      capturing = false;
      return;
    }
    // 修飾キー単体(ShiftLeft 等)は割当対象外として無視
    if (/^(Shift|Control|Alt|Meta)/.test(e.code)) return;
    pttKey = e.code;
    capturing = false;
  }

  async function save() {
    saving = true;
    try {
      await settingsApi.putVoiceInput({ mode, ptt_key: pttKey });
      pushToast('音声入力設定を保存しました', 'success');
      // store の settings を最新化(次回 ChatInput が読む値)
      await settingsStore.load();
    } catch (e) {
      pushToast(
        `保存に失敗しました: ${e instanceof Error ? e.message : String(e)}`,
        'error',
      );
    } finally {
      saving = false;
    }
  }
</script>

<svelte:window onkeydown={onWindowKeydown} />

<h3>音声入力</h3>
<p class="desc">
  チャット欄への音声入力です。認識は録音ソース機能と同じローカル Whisper エンジンで実行されます。
</p>

{#if settingsStore.settings === null}
  <!-- settings 到着前は編集 UI を出さない (AudioSettingsSection と同じゲート)。
       到着前に編集できてしまうと、上の $effect の初回同期がユーザ編集を上書きする。 -->
  <div class="loading"><Spinner /> 読み込み中…</div>
{:else}
  <fieldset class="modes">
    <legend>モード</legend>
    <label>
      <input type="radio" name="voice-mode" value="off" bind:group={mode} />
      無効
    </label>
    <label>
      <input type="radio" name="voice-mode" value="push_to_talk" bind:group={mode} />
      プッシュトゥトーク — キーを押している間だけ録音(タップは通常入力)
    </label>
    <label>
      <input type="radio" name="voice-mode" value="hands_free" bind:group={mode} />
      常時有効(ハンズフリー) — 発話を自動で区切って逐次入力
    </label>
  </fieldset>

  <div class="keyrow">
    <span class="keylabel">PTT キー</span>
    <button
      type="button"
      class="keybtn"
      disabled={mode !== 'push_to_talk'}
      onclick={startCapture}
    >
      {#if capturing}
        キーを押してください…(Esc でキャンセル)
      {:else}
        {pttKey}
      {/if}
    </button>
    <span class="keyhint">長押しで録音。textarea 入力中でも使えます。</span>
  </div>

  <div class="save">
    <button type="button" class="savebtn" disabled={saving} onclick={save}>保存</button>
  </div>
{/if}

<style>
  .desc {
    font-size: 12px;
    color: var(--color-fg-muted);
  }
  .loading {
    padding: var(--space-5);
    color: var(--color-fg-muted);
    text-align: center;
  }
  .modes {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    padding: var(--space-3);
    margin: var(--space-3) 0;
  }
  .modes label {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    font-size: 13px;
  }
  .keyrow {
    display: flex;
    align-items: center;
    gap: var(--space-3);
    margin: var(--space-3) 0;
  }
  .keylabel {
    font-size: 13px;
  }
  .keybtn {
    min-width: 120px;
    padding: var(--space-1) var(--space-3);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    background: var(--color-bg);
    font-family: var(--font-mono);
    cursor: pointer;
  }
  .keybtn:disabled {
    opacity: 0.5;
    cursor: default;
  }
  .keyhint {
    font-size: 11px;
    color: var(--color-fg-muted);
  }
  .save {
    margin-top: var(--space-3);
  }
  .savebtn {
    padding: var(--space-2) var(--space-4);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    background: var(--color-accent);
    color: #fff;
    cursor: pointer;
  }
</style>
