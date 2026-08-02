import { describe, expect, it } from 'vitest';

import { visualIndexOutcomeToast } from '$lib/api/visualIndex';

describe('visualIndexOutcomeToast', () => {
  it('完了(スキップ無し)は success', () => {
    const t = visualIndexOutcomeToast('page', { kind: 'complete', skippedPages: 0 });
    expect(t).toEqual({ message: 'ページ索引の構築が完了しました', level: 'success' });
  });

  it('部分失敗はスキップ件数を文言に出す(隠さない)', () => {
    // 最終レビュー I4: 1件でも索引できれば「完了」の見た目になるため、
    // 失敗ページ数を出さないと半滅に気付けない。
    const t = visualIndexOutcomeToast('tile', { kind: 'complete', skippedPages: 12 });
    expect(t.message).toBe('タイル索引の構築が完了しました(12件のページをスキップしました)');
    expect(t.level).toBe('info');
  });

  it('対象0件(noop)は「完了」を装わず削除の手順を案内する', () => {
    // 最終レビュー I3: パラメータを変えても索引済みソースは再構築対象にならない。
    const t = visualIndexOutcomeToast('tile', { kind: 'noop', skippedPages: 0 });
    expect(t.message).toContain('タイル索引の対象が0件でした');
    expect(t.message).toContain('先に索引を削除してください');
    expect(t.level).toBe('info');
  });

  it('全滅(error)は error', () => {
    const t = visualIndexOutcomeToast('page', { kind: 'error', skippedPages: 0 });
    expect(t).toEqual({ message: 'ページ索引の構築に失敗しました', level: 'error' });
  });

  it('単位ラベルは Modal と同じ語を使う', () => {
    expect(visualIndexOutcomeToast('page', { kind: 'error', skippedPages: 0 }).message)
      .toContain('ページ索引');
    expect(visualIndexOutcomeToast('tile', { kind: 'error', skippedPages: 0 }).message)
      .toContain('タイル索引');
  });
});
