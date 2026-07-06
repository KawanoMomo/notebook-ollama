/** PTT キーのタップ/長押し判別(spec §4 プッシュトゥトーク)。
 *
 * Claude Code の hold モードと同じ「押し方でユーザー意図を汲む」方式。
 * ブラウザは keydown/keyup + repeat フラグが取れるため、ターミナルの
 * キーリピート検出よりも素直に実装できる。
 */

export const HOLD_THRESHOLD_MS = 250;

export type PttEvent =
  | { type: 'pressStart' } // keydown 直後(音声キャプチャ先行開始用)
  | { type: 'tap' }        // しきい値未満で解放 → 呼び出し側が 1 文字挿入
  | { type: 'holdStart' }  // しきい値超え → 録音中 UI へ
  | { type: 'holdEnd' };   // 長押し解放 → 停止・変換

export interface PttKeyTrackerOptions {
  code: string; // KeyboardEvent.code(例 'Space')
  onEvent: (e: PttEvent) => void;
  holdThresholdMs?: number;
}

export function createPttKeyTracker(opts: PttKeyTrackerOptions) {
  const threshold = opts.holdThresholdMs ?? HOLD_THRESHOLD_MS;
  let pressed = false;
  let holding = false;
  let timer: ReturnType<typeof setTimeout> | null = null;

  function clearTimer() {
    if (timer !== null) {
      clearTimeout(timer);
      timer = null;
    }
  }

  return {
    /** true を返したら呼び出し側は e.preventDefault() する。 */
    handleKeydown(e: KeyboardEvent): boolean {
      // Global constraints first: repeat / isComposing / modifiers / code mismatch
      if (
        e.repeat ||
        e.code !== opts.code ||
        e.isComposing ||
        e.ctrlKey || e.altKey || e.metaKey || e.shiftKey
      ) {
        return false;
      }

      // 既に押下中は重複を無視
      if (pressed) {
        return false;
      }

      pressed = true;
      holding = false;
      opts.onEvent({ type: 'pressStart' });
      timer = setTimeout(() => {
        holding = true;
        opts.onEvent({ type: 'holdStart' });
      }, threshold);
      return true;
    },

    handleKeyup(e: KeyboardEvent): boolean {
      if (!pressed || e.code !== opts.code) return false;
      pressed = false;
      clearTimer();
      opts.onEvent({ type: holding ? 'holdEnd' : 'tap' });
      holding = false;
      return true;
    },

    /** フォーカス喪失・モード切替等で保留状態を破棄する。 */
    cancel() {
      pressed = false;
      holding = false;
      clearTimer();
    },
  };
}
