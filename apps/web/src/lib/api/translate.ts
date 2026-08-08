/**
 * 選択範囲翻訳の SSE クライアント。
 *
 * 失敗しても出典の閲覧自体は妨げないよう、例外を投げずに黙って終わる
 * (呼び出し側はトークンが1つも来なかったことで失敗を判断できる)。
 */
export async function translateStream(
  text: string,
  onToken: (t: string) => void,
  opts: { conversationId?: string; targetLang?: string } = {},
): Promise<void> {
  let res: Response;
  try {
    res = await fetch('/api/translate', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        text,
        target_lang: opts.targetLang ?? 'ja',
        conversation_id: opts.conversationId ?? null,
      }),
    });
  } catch {
    return;
  }
  if (!res.ok || !res.body) return;

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = '';
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    const parts = buf.split('\n\n');
    buf = parts.pop() ?? '';
    for (const part of parts) {
      const line = part.trim();
      if (!line.startsWith('data:')) continue;
      try {
        const payload = JSON.parse(line.slice(5).trim());
        // error / done はトークンとして流さない
        if (typeof payload.text === 'string') onToken(payload.text);
      } catch {
        // 壊れた行は無視する
      }
    }
  }
}
