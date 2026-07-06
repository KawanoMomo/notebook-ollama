/** textarea のカーソル位置(選択範囲)にテキストを挿入する(spec 決定 #4)。
 *
 * undo 履歴を保つため execCommand('insertText') を優先し(Chrome で有効)、
 * 使えない環境(jsdom 等)では value splice にフォールバックする。
 * 戻り値は挿入後の全文(呼び出し側の $state 同期用)。
 */
export function insertAtCursor(textarea: HTMLTextAreaElement, text: string): string {
  const start = textarea.selectionStart ?? textarea.value.length;
  const end = textarea.selectionEnd ?? start;
  textarea.focus();
  let inserted = false;
  try {
    inserted = document.execCommand('insertText', false, text);
  } catch {
    inserted = false;
  }
  if (!inserted) {
    textarea.value = textarea.value.slice(0, start) + text + textarea.value.slice(end);
    const pos = start + text.length;
    textarea.setSelectionRange(pos, pos);
  }
  return textarea.value;
}
