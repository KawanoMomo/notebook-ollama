import type { EvidenceSpan } from '$lib/api/types';

/**
 * 第2段(埋め込み類似)の遅延解決。
 * 失敗しても閲覧を妨げないよう、例外を投げず空配列を返す。
 */
export async function resolveSpans(
  messageId: string,
  n: number,
  answerOccurrence: number,
): Promise<EvidenceSpan[]> {
  try {
    const res = await fetch(`/api/messages/${messageId}/citations/${n}/spans`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ answer_occurrence: answerOccurrence }),
    });
    if (!res.ok) return [];
    const body = await res.json();
    return body.spans ?? [];
  } catch {
    return [];
  }
}
