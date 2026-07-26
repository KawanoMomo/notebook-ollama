/**
 * formatChatStreamError — SSE開始前エラーの整形(実機FB 2026-07-26:
 * モデル不在404が「chat stream failed: 404 {生JSON}」で表示され対処不明だった)。
 */
import { describe, expect, it } from 'vitest';
import { formatChatStreamError } from '$lib/api/chat';

describe('formatChatStreamError', () => {
  it('AppError封筒からメッセージ+対処を取り出す', () => {
    const body = JSON.stringify({
      error: {
        code: 'ollama.model_not_found',
        message: 'モデル X が Ollama に見つかりません',
        remediation: '既定モデルを変更してください。',
      },
    });
    const out = formatChatStreamError(404, body);
    expect(out).toContain('見つかりません');
    expect(out).toContain('既定モデルを変更');
    expect(out).not.toContain('{'); // 生JSONを見せない
  });

  it('remediation無しならメッセージのみ', () => {
    const body = JSON.stringify({ error: { message: 'エラーです' } });
    expect(formatChatStreamError(400, body)).toBe('エラーです');
  });

  it('JSONでないボディはHTTPステータス付きで生表示', () => {
    const out = formatChatStreamError(502, 'Bad Gateway');
    expect(out).toContain('502');
    expect(out).toContain('Bad Gateway');
  });
});
