/**
 * 打ち切り警告注記(core/generation/stream.py の TRUNCATION_NOTE_PREFIX と
 * 同じ意味論)。BE が保存する assistant 全文の末尾に付く。
 *
 * FE 側での用途: 手動継続(continueLast)の prefill シード。旧注記を残したまま
 * streamingText に載せると、継続ストリーミング中ずっと本文中央に警告が
 * 挟まって見えてしまうため、除去してから継続表示を開始する(issue #22)。
 */
export const TRUNCATION_NOTE_PREFIX = '\n\n---\n⚠️ 応答が出力トークン上限';

/** 本文末尾の打ち切り注記を取り除く(core/generation/stream.py:strip_truncation_note と同じ意味論)。 */
export function stripTruncationNote(text: string): string {
  const idx = text.lastIndexOf(TRUNCATION_NOTE_PREFIX);
  return idx >= 0 ? text.slice(0, idx) : text;
}
