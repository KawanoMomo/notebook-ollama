import { describe, expect, it } from 'vitest';
import { insertAtCursor } from '$lib/utils/textInsert';

function makeTextarea(value: string, start: number, end = start): HTMLTextAreaElement {
  const ta = document.createElement('textarea');
  document.body.appendChild(ta);
  ta.value = value;
  ta.setSelectionRange(start, end);
  return ta;
}

describe('insertAtCursor', () => {
  it('カーソル位置に挿入しカーソルは挿入末尾へ', () => {
    const ta = makeTextarea('前後', 1);
    const result = insertAtCursor(ta, '中');
    expect(result).toBe('前中後');
    expect(ta.selectionStart).toBe(2);
    expect(ta.selectionEnd).toBe(2);
  });

  it('選択範囲は置換される', () => {
    const ta = makeTextarea('ABCDE', 1, 4);
    const result = insertAtCursor(ta, 'x');
    expect(result).toBe('AxE');
    expect(ta.selectionStart).toBe(2);
  });

  it('末尾カーソルでは追記になる', () => {
    const ta = makeTextarea('こんにちは', 5);
    const result = insertAtCursor(ta, '、世界');
    expect(result).toBe('こんにちは、世界');
  });
});
