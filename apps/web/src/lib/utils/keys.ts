export interface ShortcutBinding {
  combo: string; // e.g. "Mod+K", "Mod+/", "Mod+B", "Mod+Enter"
  handler: (e: KeyboardEvent) => void;
  /** when true, fires even when an input/textarea has focus */
  allowInInput?: boolean;
  /**
   * 条件付きバインディング用ゲート。false を返す間は matches() 判定自体を行わない
   * (preventDefault も呼ばれない)。ハンドラ内で早期 return するだけだと、bare な
   * ArrowLeft/ArrowRight/Space のようなブラウザ既定動作を持つキーは、条件を満たさない
   * 状態でも preventDefault() されてしまう(例: フォーカス中のボタンが Space で
   * 反応しなくなる)ため、条件はここで弾く。
   */
  enabled?: () => boolean;
}

// e.key の別名。空白キーは e.key === ' '(スペース1文字)で届くため、combo 側で
// 'Space' と書けるようにここで正規化する(combo 文字列は '+' で分割・trim されるため
// combo: ' ' はそのままでは書けない)。
const KEY_ALIASES: Record<string, string> = { ' ': 'space' };

function normalizeKey(key: string): string {
  return (KEY_ALIASES[key] ?? key).toLowerCase();
}

function matches(combo: string, e: KeyboardEvent): boolean {
  const parts = combo.toLowerCase().split('+').map((p) => p.trim());
  const mod = parts.includes('mod');
  const shift = parts.includes('shift');
  const alt = parts.includes('alt');
  const ctrl = parts.includes('ctrl');
  const key = parts.filter((p) => !['mod', 'shift', 'alt', 'ctrl'].includes(p))[0] ?? '';
  const isMac = typeof navigator !== 'undefined' && /Mac/i.test(navigator.platform);
  const modOk = mod ? (isMac ? e.metaKey : e.ctrlKey) : true;
  const ctrlOk = ctrl ? e.ctrlKey : true;
  const shiftOk = shift ? e.shiftKey : !e.shiftKey || key === '';
  const altOk = alt ? e.altKey : !e.altKey || key === '';
  return (
    modOk &&
    ctrlOk &&
    shiftOk &&
    altOk &&
    normalizeKey(e.key) === key
  );
}

function isInInput(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName.toLowerCase();
  return tag === 'input' || tag === 'textarea' || target.isContentEditable;
}

export function bindShortcuts(bindings: ShortcutBinding[]): () => void {
  const handler = (e: KeyboardEvent) => {
    for (const b of bindings) {
      if (b.enabled && !b.enabled()) continue;
      if (!b.allowInInput && isInInput(e.target)) continue;
      if (matches(b.combo, e)) {
        e.preventDefault();
        b.handler(e);
        return;
      }
    }
  };
  window.addEventListener('keydown', handler);
  return () => window.removeEventListener('keydown', handler);
}
