export interface ShortcutBinding {
  combo: string; // e.g. "Mod+K", "Mod+/", "Mod+B", "Mod+Enter"
  handler: (e: KeyboardEvent) => void;
  /** when true, fires even when an input/textarea has focus */
  allowInInput?: boolean;
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
    e.key.toLowerCase() === key
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
