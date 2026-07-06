<script lang="ts">
  import Button from './Button.svelte';
  import PromptToolbar from './PromptToolbar.svelte';
  import { Send, Square, AlertCircle, Mic, Loader2 } from '@lucide/svelte';
  import { promptsStore } from '$lib/stores/prompts.svelte';
  import { settingsStore } from '$lib/stores/settings.svelte';
  import { voiceInputStore } from '$lib/stores/voiceInput.svelte';
  import { createPttKeyTracker } from '$lib/audio/pttKey';
  import { insertAtCursor } from '$lib/utils/textInsert';
  import { pushToast } from './Toast.svelte';
  import { onMount } from 'svelte';

  interface Props {
    streaming: boolean;
    hint?: string | null;
    /** 現在チェック済みのソース数(0 の場合は送信不可+警告)。 */
    sourcesSelected?: number;
    onSend: (text: string) => void;
    onCancel: () => void;
  }
  let {
    streaming,
    hint = null,
    sourcesSelected = 1,
    onSend,
    onCancel,
  }: Props = $props();

  onMount(() => {
    if (!promptsStore.prompts) {
      promptsStore.load().catch(() => {
        /* degraded: ツールバー非表示で続行(設計 §6.2) */
      });
    }
    if (!settingsStore.settings) {
      settingsStore.load().catch(() => {
        /* degraded: 音声入力は既定値(push_to_talk/Space)で動作 */
      });
    }
    voiceInputStore.setCallbacks({
      onText: (text) => {
        if (textareaEl) value = insertAtCursor(textareaEl, text);
      },
      onError: (message) => pushToast(message, 'error'),
    });
    return () => {
      tracker.cancel(); // 保留中のホールド判定タイマーを破棄
      voiceInputStore.stopAll();
    };
  });

  let value = $state('');
  let textareaEl = $state<HTMLTextAreaElement | null>(null);

  const noSourcesSelected = $derived(sourcesSelected <= 0);
  const voiceMode = $derived(settingsStore.settings?.voice_input?.mode ?? 'push_to_talk');
  const pttCode = $derived(settingsStore.settings?.voice_input?.ptt_key ?? 'Space');
  const voiceStatus = $derived(voiceInputStore.status);
  const voiceBusy = $derived(voiceStatus === 'transcribing');
  const voiceActive = $derived(voiceStatus === 'recording' || voiceStatus === 'handsfree');

  // ---- PTT キーフック(spec §4: タップ=通常入力 / 長押し=録音) ----
  // tracker はキー変更に追随して作り直す。$derived.by で明示的に前インスタンスを
  // cancel() してから差し替える(素の $derived だと再評価タイミングで保留中の
  // ホールド判定タイマーが孤児化しうるため)。
  let prevTracker: ReturnType<typeof createPttKeyTracker> | null = null;
  const tracker = $derived.by(() => {
    // pttCode / voiceMode を購読して再評価トリガにする
    const code = pttCode;
    const mode = voiceMode;
    if (prevTracker) prevTracker.cancel();
    const next = createPttKeyTracker({
      code,
      onEvent: (ev) => {
        if (mode === 'push_to_talk') {
          if (ev.type === 'pressStart') {
            // キャプチャは長押し確定(holdStart)まで開始しない(spec §4 改訂: Fix 2)。
            // タップかもしれない段階で getUserMedia を叩くと、通常タイピング中の
            // 単打鍵のたびにマイクインジケーターが点滅してしまうため。
          } else if (ev.type === 'tap') {
            // タップは通常入力: 何も開始していないので pttTapCancel は呼ばない。
            // textarea フォーカス中なら 1 打鍵分を挿入
            if (textareaEl && document.activeElement === textareaEl) {
              value = insertAtCursor(textareaEl, keyChar(code));
            }
          } else if (ev.type === 'holdStart') {
            // 長押し確定した瞬間にキャプチャ開始→即録音状態へ(pttPressStart が
            // 'capturing' をセットし、pttHoldStart がその場で 'recording' へ進める)
            voiceInputStore.pttPressStart();
            voiceInputStore.pttHoldStart();
          } else if (ev.type === 'holdEnd') void voiceInputStore.pttHoldEnd();
        } else if (mode === 'hands_free') {
          // ハンズフリーは長押しでトグル(タップは通常入力のまま)
          if (ev.type === 'tap' && textareaEl && document.activeElement === textareaEl) {
            value = insertAtCursor(textareaEl, keyChar(code));
          } else if (ev.type === 'holdStart') void voiceInputStore.handsFreeToggle();
        }
      },
    });
    prevTracker = next;
    return next;
  });

  /** KeyboardEvent.code → 挿入すべき文字(印字キーのみ)。 */
  function keyChar(code: string): string {
    if (code === 'Space') return ' ';
    if (code.startsWith('Key')) return code.slice(3).toLowerCase();
    if (code.startsWith('Digit')) return code.slice(5);
    return ''; // F9 等の非印字キーは挿入なし
  }

  /** チャット textarea 以外のインタラクティブ要素にフォーカス中は PTT フックを介入させない
   *  (Fix 1: SourcesPanel のボタン等が Space で反応できなくなる問題の回避)。 */
  const INTERACTIVE_SELECTOR =
    'button, a[href], input, select, textarea, [contenteditable="true"], [role="button"]';
  function isForeignInteractiveTarget(e: KeyboardEvent): boolean {
    const el = e.target as HTMLElement | null;
    if (!el || typeof el.closest !== 'function') return false;
    const interactive = el.closest(INTERACTIVE_SELECTOR);
    if (!interactive) return false; // document.body 等は素通しで PTT フック対象
    return interactive !== textareaEl; // チャット textarea 自身は対象内
  }

  function onDocKeydown(e: KeyboardEvent) {
    if (voiceMode === 'off') return;
    if (isForeignInteractiveTarget(e)) return;
    if (tracker.handleKeydown(e)) e.preventDefault();
  }
  function onDocKeyup(e: KeyboardEvent) {
    if (voiceMode === 'off') return;
    if (tracker.handleKeyup(e)) e.preventDefault();
  }

  // ---- マイクボタン(mouse/touch)----
  function onMicPointerDown() {
    if (voiceMode !== 'push_to_talk' || voiceBusy) return;
    voiceInputStore.pttPressStart();
    voiceInputStore.pttHoldStart(); // ボタンはタップ判定不要: 押下で即録音
  }
  function onMicPointerUp() {
    if (voiceMode !== 'push_to_talk') return;
    void voiceInputStore.pttHoldEnd();
  }
  function onMicClick() {
    if (voiceMode === 'hands_free') void voiceInputStore.handsFreeToggle();
  }

  function onKey(e: KeyboardEvent) {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      submit();
    }
  }

  function submit() {
    if (streaming) return;
    if (noSourcesSelected) return;
    const t = value.trim();
    if (!t) return;
    onSend(t);
    value = '';
  }
</script>

<svelte:document onkeydown={onDocKeydown} onkeyup={onDocKeyup} />

{#if noSourcesSelected}
  <div class="warn" role="alert">
    <AlertCircle size="14" />
    <span>ソースが選択されていません。1 つ以上選んでください。</span>
  </div>
{/if}
<PromptToolbar
  prompts={promptsStore.prompts}
  {streaming}
  {sourcesSelected}
  onSend={(body) => {
    if (streaming || noSourcesSelected) return;
    onSend(body);
  }}
/>
<form class="input" onsubmit={(e) => { e.preventDefault(); submit(); }}>
  <textarea
    bind:value
    bind:this={textareaEl}
    placeholder="質問を入力（Cmd/Ctrl+Enter で送信）"
    rows="3"
    onkeydown={onKey}
  ></textarea>
  <div class="row">
    <span class="hint">
      {#if voiceStatus === 'recording'}
        録音中… {voiceInputStore.elapsedSec}s(離すと変換)
      {:else if voiceStatus === 'transcribing'}
        変換中…
      {:else if voiceStatus === 'handsfree'}
        ハンズフリー認識中(ボタンで停止)
      {:else}
        {hint ?? ''}
      {/if}
    </span>
    <div class="actions">
      {#if voiceMode !== 'off'}
        <button
          type="button"
          class="mic"
          class:active={voiceActive}
          aria-label="音声入力"
          aria-pressed={voiceActive}
          disabled={voiceBusy}
          onpointerdown={onMicPointerDown}
          onpointerup={onMicPointerUp}
          onpointerleave={onMicPointerUp}
          onclick={onMicClick}
        >
          {#if voiceBusy}
            <Loader2 size={14} class="spin" />
          {:else}
            <Mic size={14} />
          {/if}
        </button>
      {/if}
      {#if streaming}
        <Button type="button" variant="danger" onclick={onCancel}>
          <Square size={14} /> 停止
        </Button>
      {:else}
        <Button type="submit" disabled={noSourcesSelected}>
          <Send size={14} /> 送信
        </Button>
      {/if}
    </div>
  </div>
</form>

<style>
  .input {
    padding: var(--space-3);
    border-top: 1px solid var(--color-border);
    background: var(--color-bg);
  }
  textarea {
    width: 100%;
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    padding: var(--space-2) var(--space-3);
    resize: vertical;
    min-height: 60px;
    font-size: 14px;
  }
  textarea:focus {
    outline: none;
    border-color: var(--color-accent);
  }
  .row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-top: var(--space-2);
  }
  .hint {
    font-size: 11px;
    color: var(--color-fg-muted);
  }
  .actions {
    display: flex;
    align-items: center;
    gap: var(--space-2);
  }
  .mic {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 28px;
    height: 28px;
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    background: var(--color-bg);
    cursor: pointer;
  }
  .mic.active {
    border-color: var(--color-error);
    color: var(--color-error);
    animation: mic-pulse 1.2s ease-in-out infinite;
  }
  .mic:disabled {
    opacity: 0.6;
    cursor: default;
  }
  @keyframes mic-pulse {
    0%, 100% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--color-error) 35%, transparent); }
    50% { box-shadow: 0 0 0 4px color-mix(in srgb, var(--color-error) 15%, transparent); }
  }
  :global(.mic .spin) {
    animation: mic-spin 1s linear infinite;
  }
  @keyframes mic-spin {
    to { transform: rotate(360deg); }
  }
  .warn {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    background: #fff7ed;
    color: #c2410c;
    padding: var(--space-2) var(--space-3);
    border-top: 1px solid #fed7aa;
    border-bottom: 1px solid #fed7aa;
    font-size: 12px;
  }
</style>
