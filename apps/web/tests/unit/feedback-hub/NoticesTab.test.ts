/**
 * NoticesTab — Linear 風 timeline (Sprint 6 Task 6.2)
 *
 * spec: docs/specs/2026-06-28-crash-report-feedback-hub-design.md §5.3
 * plan: docs/superpowers/plans/2026-06-28-crash-report-feedback-hub.md Task 6.2
 *
 * NoticesStore は DI 可能 (`store` prop)。テスト中はモック API を渡した
 * 専用インスタンスで描画し、グローバル singleton の状態漏れを避ける。
 *
 * Sprint 5 lessons (per parent agent):
 * - vitest 単体 GREEN だけでは Playwright で 5 件の wiring/visual 欠陥が出た。
 *   そのため、本テストでは store reactivity (markSeen → unreadCount 減少) を
 *   コンポーネント側のクリックハンドラ経由で検証し、視覚は CSS class で確認する。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import NoticesTab from '$lib/components/feedback-hub/NoticesTab.svelte';
import { createNoticesStore } from '$lib/stores/notices.svelte';
import type { Notice } from '$lib/api/types';

// ---------------------------------------------------------------------------
// helpers
// ---------------------------------------------------------------------------

const STORAGE_KEY = 'seen_notice_ids';

function seedSeen(ids: string[]) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(ids));
}

function makeNotice(overrides: Partial<Notice> = {}): Notice {
  return {
    id: 'n1',
    date: '2026-06-28',
    title: 'お知らせタイトル',
    body: 'お知らせ本文です。',
    subsections: null,
    ...overrides,
  };
}

function makeApi(items: Notice[] = []) {
  return { listNotices: vi.fn().mockResolvedValue(items) };
}

function deferred<T>() {
  let resolve!: (v: T) => void;
  let reject!: (e: Error) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

const SEED_TWO: Notice[] = [
  {
    id: '2026-06-28-crash-report-feedback-hub',
    date: '2026-06-28',
    title: 'クラッシュレポート & フィードバックハブを公開しました',
    body: 'ヘッダの拡声器アイコンから「お知らせ」「不具合を報告」「ご意見・ご要望」を 1 か所で送れるようになりました。',
    subsections: [
      {
        heading: '新機能',
        items: [
          'ヘッダの拡声器から お知らせ / 不具合 / ご意見 タブを表示',
          'クラッシュ自動検知 (FastAPI 例外 / 異常終了 / フロント onerror)',
        ],
      },
      {
        heading: '改善',
        items: ['構造化ログをホワイトリスト方式で検疫し、PII リークを防止'],
      },
    ],
  },
  {
    id: '2026-06-28-pr4-release-notes',
    date: '2026-06-28',
    title: 'リリースノート: PR #4 統合',
    body: 'クラッシュレポート / フィードバックハブの PR #4 を統合しました。',
    subsections: null,
  },
];

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => cleanup());

// ---------------------------------------------------------------------------
// 描画 — items を取得して timeline に並べる
// ---------------------------------------------------------------------------

describe('NoticesTab — 描画 (timeline)', () => {
  it('mount 時に store.load() を呼ぶ (items が空のとき)', async () => {
    const api = makeApi(SEED_TWO);
    const store = createNoticesStore(api as never);
    render(NoticesTab, { store });
    await waitFor(() => expect(api.listNotices).toHaveBeenCalledTimes(1));
  });

  it('既に items がロード済みなら mount 時に load() を呼ばない', async () => {
    const api = makeApi(SEED_TWO);
    const store = createNoticesStore(api as never);
    await store.load(); // 事前ロード
    api.listNotices.mockClear();
    render(NoticesTab, { store });
    // onMount が走ってから少し待ったうえで非呼び出しを確認
    await new Promise((r) => setTimeout(r, 30));
    expect(api.listNotices).not.toHaveBeenCalled();
  });

  it('2 件の seed notice を全て描画する (タイトル / 本文)', async () => {
    const api = makeApi(SEED_TWO);
    const store = createNoticesStore(api as never);
    render(NoticesTab, { store });

    await waitFor(() => {
      expect(
        screen.getByText('クラッシュレポート & フィードバックハブを公開しました'),
      ).toBeDefined();
    });
    expect(screen.getByText('リリースノート: PR #4 統合')).toBeDefined();
    expect(screen.getByText(/PR #4 を統合しました/)).toBeDefined();
  });

  it('subsections (見出し + 箇条書き) を描画する', async () => {
    const store = createNoticesStore(makeApi(SEED_TWO) as never);
    render(NoticesTab, { store });

    await waitFor(() => expect(screen.getByText('新機能')).toBeDefined());
    expect(screen.getByText('改善')).toBeDefined();
    expect(
      screen.getByText('ヘッダの拡声器から お知らせ / 不具合 / ご意見 タブを表示'),
    ).toBeDefined();
    expect(
      screen.getByText('構造化ログをホワイトリスト方式で検疫し、PII リークを防止'),
    ).toBeDefined();
  });

  it('subsections=null のエントリでもクラッシュせず本文だけ出る', async () => {
    const store = createNoticesStore(
      makeApi([makeNotice({ id: 'solo', subsections: null })]) as never,
    );
    render(NoticesTab, { store });

    await waitFor(() => expect(screen.getByText('お知らせ本文です。')).toBeDefined());
  });

  it('日付ヘッダを「YYYY年M月D日」(和暦表記) で描画する', async () => {
    const store = createNoticesStore(makeApi(SEED_TWO) as never);
    render(NoticesTab, { store });

    await waitFor(() => {
      const header = screen.getByText(/2026年6月28日/);
      expect(header.textContent).toMatch(/年/);
      expect(header.textContent).toMatch(/月/);
      expect(header.textContent).toMatch(/日/);
    });
  });

  it('同一日付の複数エントリは 1 つの日付ヘッダ配下にグループ化される', async () => {
    const store = createNoticesStore(makeApi(SEED_TWO) as never);
    render(NoticesTab, { store });

    await waitFor(() => expect(screen.getAllByRole('article').length).toBe(2));
    const headers = screen.getAllByText(/2026年6月28日/);
    expect(headers).toHaveLength(1);
  });

  it('日付が異なるエントリは降順 (新しい日付が上) に並ぶ', async () => {
    const store = createNoticesStore(
      makeApi([
        makeNotice({ id: 'old', date: '2026-05-01', title: '古いお知らせ' }),
        makeNotice({ id: 'new', date: '2026-06-28', title: '新しいお知らせ' }),
      ]) as never,
    );
    const { container } = render(NoticesTab, { store });

    await waitFor(() => expect(screen.getAllByRole('article').length).toBe(2));
    const headers = container.querySelectorAll('.date-header');
    expect(headers).toHaveLength(2);
    // 上のヘッダが新しい日付
    expect(headers[0].textContent).toMatch(/2026年6月28日/);
    expect(headers[1].textContent).toMatch(/2026年5月1日/);
  });
});

// ---------------------------------------------------------------------------
// 未読マーカー
// ---------------------------------------------------------------------------

describe('NoticesTab — 未読マーカー (青ドット)', () => {
  it('seenIds にない notice には .unread クラスが付く', async () => {
    seedSeen([]); // 全件未読
    const store = createNoticesStore(makeApi(SEED_TWO) as never);
    render(NoticesTab, { store });

    await waitFor(() => expect(screen.getAllByRole('article').length).toBe(2));
    const entries = screen.getAllByRole('article');
    for (const e of entries) {
      expect(e.classList.contains('unread')).toBe(true);
    }
  });

  it('seenIds に含まれる notice には .unread が付かない', async () => {
    seedSeen(['2026-06-28-pr4-release-notes']); // 2 件目だけ既読
    const store = createNoticesStore(makeApi(SEED_TWO) as never);
    render(NoticesTab, { store });

    await waitFor(() => expect(screen.getAllByRole('article').length).toBe(2));
    // タイトルから article を逆引きする方が確実
    const seenArticle = screen
      .getByText('リリースノート: PR #4 統合')
      .closest('article');
    const unreadArticle = screen
      .getByText('クラッシュレポート & フィードバックハブを公開しました')
      .closest('article');
    expect(seenArticle?.classList.contains('unread')).toBe(false);
    expect(unreadArticle?.classList.contains('unread')).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// クリックで markSeen
// ---------------------------------------------------------------------------

describe('NoticesTab — クリックで既読化', () => {
  it('エントリクリックで store.markSeen(id) が呼ばれる', async () => {
    const store = createNoticesStore(makeApi(SEED_TWO) as never);
    const spy = vi.spyOn(store, 'markSeen');
    render(NoticesTab, { store });

    await waitFor(() => expect(screen.getAllByRole('article').length).toBe(2));
    const target = screen
      .getByText('クラッシュレポート & フィードバックハブを公開しました')
      .closest('article') as HTMLElement;
    await fireEvent.click(target);

    expect(spy).toHaveBeenCalledWith('2026-06-28-crash-report-feedback-hub');
  });

  it('クリック後に unreadCount が 1 減り、当該 entry の .unread が外れる', async () => {
    const store = createNoticesStore(makeApi(SEED_TWO) as never);
    render(NoticesTab, { store });

    await waitFor(() => expect(screen.getAllByRole('article').length).toBe(2));
    expect(store.unreadCount).toBe(2);

    const target = screen
      .getByText('リリースノート: PR #4 統合')
      .closest('article') as HTMLElement;
    await fireEvent.click(target);

    // 反応的更新を待つ
    await waitFor(() => expect(store.unreadCount).toBe(1));
    const after = screen
      .getByText('リリースノート: PR #4 統合')
      .closest('article') as HTMLElement;
    expect(after.classList.contains('unread')).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// loading / empty / error 状態
// ---------------------------------------------------------------------------

describe('NoticesTab — loading state', () => {
  it('items=[] かつ load() 進行中はスピナー (role=status) を出す', async () => {
    const d = deferred<Notice[]>();
    const api = { listNotices: vi.fn().mockReturnValue(d.promise) };
    const store = createNoticesStore(api as never);
    render(NoticesTab, { store });

    // onMount が走って loading=true になるまで待つ
    await waitFor(() => expect(screen.getByRole('status')).toBeDefined());
    // promise を解決してテストをクリーンに終わらせる
    d.resolve([]);
  });
});

describe('NoticesTab — empty state', () => {
  it('items=[] かつ load() 完了で「お知らせはありません」を出す', async () => {
    const store = createNoticesStore(makeApi([]) as never);
    render(NoticesTab, { store });

    await waitFor(() => expect(screen.getByText('お知らせはありません')).toBeDefined());
    expect(screen.queryByRole('status')).toBeNull();
  });
});

describe('NoticesTab — error state', () => {
  it('load() が reject したら「お知らせの取得に失敗しました」と再試行ボタンを出す', async () => {
    const api = {
      listNotices: vi.fn().mockRejectedValue(new Error('network down')),
    };
    const store = createNoticesStore(api as never);
    render(NoticesTab, { store });

    await waitFor(() =>
      expect(screen.getByText('お知らせの取得に失敗しました')).toBeDefined(),
    );
    expect(screen.getByRole('button', { name: /再試行/ })).toBeDefined();
  });

  it('再試行ボタンで listNotices が再度呼ばれ、成功すれば timeline が出る', async () => {
    const api = {
      listNotices: vi
        .fn()
        .mockRejectedValueOnce(new Error('network down'))
        .mockResolvedValueOnce(SEED_TWO),
    };
    const store = createNoticesStore(api as never);
    render(NoticesTab, { store });

    await waitFor(() =>
      expect(screen.getByText('お知らせの取得に失敗しました')).toBeDefined(),
    );
    await fireEvent.click(screen.getByRole('button', { name: /再試行/ }));
    await waitFor(() =>
      expect(
        screen.getByText('クラッシュレポート & フィードバックハブを公開しました'),
      ).toBeDefined(),
    );
    expect(api.listNotices).toHaveBeenCalledTimes(2);
  });
});
