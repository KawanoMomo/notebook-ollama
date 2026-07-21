import { describe, expect, it } from 'vitest';
import { stripTruncationNote, TRUNCATION_NOTE_PREFIX } from '$lib/utils/truncation';

describe('stripTruncationNote', () => {
  it('注記ありの本文から注記を除去する(core/generation/stream.py:strip_truncation_note と同じ意味論)', () => {
    const body = '回答本文';
    const note = `${TRUNCATION_NOTE_PREFIX}(1024×3回)に達したため打ち切られました。`;
    expect(stripTruncationNote(body + note)).toBe(body);
  });

  it('注記なしの本文はそのまま返す', () => {
    const body = '注記のない普通の回答';
    expect(stripTruncationNote(body)).toBe(body);
  });

  it('継続失敗変種の注記文言でも除去できる', () => {
    const body = '前半の本文';
    const note = `${TRUNCATION_NOTE_PREFIX}(512×1回)に達したのち、続きの生成に失敗したため途中までの応答を表示しています。`;
    expect(stripTruncationNote(body + note)).toBe(body);
  });
});
