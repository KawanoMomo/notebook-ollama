<script lang="ts">
  /**
   * CrashDetectionModal — フロント errorBoundary が新規例外を捕捉した直後に
   * 中央へ即時表示する警告モーダル。
   *
   * spec: docs/specs/2026-06-28-crash-report-feedback-hub-design.md §5.6
   * plan: docs/superpowers/plans/2026-06-28-crash-report-feedback-hub.md Task 5.6
   *
   * 設計判断:
   * - Modal.svelte (既存) は backdrop クリックで閉じる仕様だが、本モーダルは
   *   spec §5.6 で「『今は送らない』明示クリック必須」とされているため
   *   再利用せず独立コンポーネントとして書く。
   * - 「以下のデータが送信されます / されません」のリストは
   *   [[feedback-no-data-guarantee-in-ui]] に従い **絶対に出さない**。
   *   送信内容は次の画面 (CrashPreviewDialog, Task 5.7) で実物を見せて合意する。
   */
  import Button from './Button.svelte';
  import type { PendingCrash } from '$lib/api/types';

  interface Props {
    crash: PendingCrash;
    /** 「今は送らない」または ESC で呼ばれる。 */
    onDismiss: () => void;
    /** 「送信内容をプレビュー →」で呼ばれる (CrashPreviewDialog を開く責務は親)。 */
    onPreview: (crash: PendingCrash) => void;
  }

  let { crash, onDismiss, onPreview }: Props = $props();

  function onKey(e: KeyboardEvent) {
    if (e.key === 'Escape') onDismiss();
  }
</script>

<svelte:window onkeydown={onKey} />

<!--
  data-testid を付けるのは vitest 上で backdrop / dialog 要素を直接掴むため。
  role="presentation" は backdrop が装飾要素であることを示す。
-->
<div class="backdrop" role="presentation" data-testid="crash-modal-backdrop">
  <div
    class="dialog"
    role="alertdialog"
    aria-modal="true"
    aria-labelledby="crash-detection-title"
  >
    <header>
      <h2 id="crash-detection-title">⚠ エラーが発生しました</h2>
    </header>
    <div class="body">
      <pre class="summary" data-testid="crash-summary">{crash.exception_type}{crash.exception_message ? `: ${crash.exception_message}` : ''}</pre>
      <p class="guidance">
        このエラーを開発者に報告できます。<strong
          >次の画面で送信内容のプレビューが表示されます。</strong
        >内容を確認・編集してから送信できます。
      </p>
    </div>
    <footer class="actions">
      <Button variant="secondary" onclick={onDismiss}>今は送らない</Button>
      <Button variant="primary" onclick={() => onPreview(crash)}
        >送信内容をプレビュー →</Button
      >
    </footer>
  </div>
</div>

<style>
  .backdrop {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.55);
    display: flex;
    justify-content: center;
    align-items: center;
    /* CrashPreviewDialog (Task 5.7) より上、通常 Modal より上に置く */
    z-index: 200;
  }
  .dialog {
    background: var(--color-bg);
    border-radius: var(--radius-lg);
    min-width: 480px;
    max-width: 90vw;
    max-height: 90vh;
    display: flex;
    flex-direction: column;
    box-shadow: 0 20px 40px rgba(0, 0, 0, 0.4);
  }
  header {
    padding: var(--space-4);
    border-bottom: 1px solid var(--color-border);
  }
  header h2 {
    margin: 0;
    font-size: 16px;
    font-weight: 600;
    /* spec §5.6: ヘッダ色 #ef4444 */
    color: #ef4444;
  }
  .body {
    padding: var(--space-4);
    overflow: auto;
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
  }
  .summary {
    margin: 0;
    padding: var(--space-3);
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    font-size: 12px;
    line-height: 1.5;
    background: var(--color-bg-elevated);
    /* spec §5.6: border-left: 3px solid #ef4444 */
    border-left: 3px solid #ef4444;
    border-radius: var(--radius-sm);
    white-space: pre-wrap;
    word-break: break-word;
    max-height: 240px;
    overflow: auto;
  }
  .guidance {
    margin: 0;
    font-size: 13px;
    line-height: 1.6;
    color: var(--color-fg);
  }
  .actions {
    display: flex;
    gap: var(--space-2);
    justify-content: flex-end;
    padding: var(--space-3) var(--space-4);
    border-top: 1px solid var(--color-border);
  }
</style>
