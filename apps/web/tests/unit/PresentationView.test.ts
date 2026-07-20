import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/svelte';

// vi.hoisted で巻き上げ。vi.mock factory より先に評価されることを保証する
// (AppHeader.test.ts と同じパターン。トップレベル const を factory 内で直接参照すると
// "Cannot access before initialization" になる — vi.mock 呼び出し自体が hoist される)。
const pres = vi.hoisted(() => ({
  active: true, parentSourceId: 'SRC', parentTitle: '資料A',
  page: 2, totalPages: 10,
  setTotalPages: vi.fn(), next: vi.fn(), prev: vi.fn(), goto: vi.fn(),
  start: vi.fn(), end: vi.fn(), resume: vi.fn(),
}));
vi.mock('$lib/stores/presentation.svelte', () => ({ presentationStore: pres }));
// SlideView は canvas/pdf.js を使うため差し替え(描画は evaluator ゲートで実機検証)
vi.mock('$lib/components/SlideView.svelte', async () => {
  const Stub = (await import('./stubs/SlideViewStub.svelte')).default;
  return { default: Stub };
});

import PresentationView from '$lib/components/PresentationView.svelte';

beforeEach(() => vi.clearAllMocks());

describe('PresentationView', () => {
  it('ページ位置バーが N / M 形式で表示され、◀▶で prev/next', async () => {
    render(PresentationView, { props: { notebookId: 'nb1' } });
    expect(screen.getByText('2 / 10')).toBeTruthy();
    await fireEvent.click(screen.getByRole('button', { name: '前のページ' }));
    expect(pres.prev).toHaveBeenCalled();
    await fireEvent.click(screen.getByRole('button', { name: '次のページ' }));
    expect(pres.next).toHaveBeenCalled();
  });

  it('ホイール下で next、150ms 以内の連続ホイールは無視', async () => {
    render(PresentationView, { props: { notebookId: 'nb1' } });
    const area = screen.getByTestId('slide-area');
    await fireEvent.wheel(area, { deltaY: 100 });
    await fireEvent.wheel(area, { deltaY: 100 }); // throttle 内
    expect(pres.next).toHaveBeenCalledTimes(1);
    await new Promise((r) => setTimeout(r, 160));
    await fireEvent.wheel(area, { deltaY: -100 });
    expect(pres.prev).toHaveBeenCalledTimes(1);
  });

  it('ページ番号クリック→入力→Enter で goto', async () => {
    render(PresentationView, { props: { notebookId: 'nb1' } });
    await fireEvent.click(screen.getByText('2 / 10'));
    const input = screen.getByRole('spinbutton');
    await fireEvent.input(input, { target: { value: '7' } });
    await fireEvent.keyDown(input, { key: 'Enter' });
    expect(pres.goto).toHaveBeenCalledWith(7);
  });
});
