/**
 * FeedbackTab — 「ご意見・ご要望」タブ (Sprint 8 Task 8.3)
 *
 * spec : docs/specs/2026-06-28-crash-report-feedback-hub-design.md §5.5
 * plan : docs/superpowers/plans/2026-06-28-crash-report-feedback-hub.md Task 8.3
 *
 * 検証観点:
 *
 * - 描画: 3 種別チップ + 本文 textarea + Thumbs 3 ボタン + スクショカード
 *         + フッタ 2 ボタンが全部 1 回で出る。
 * - 種別チップ: クリックで kind 更新 → placeholder が切り替わる。
 * - 本文: 入力で body state (= textarea.value) が反映され、disabled 解除のトリガになる。
 * - Thumbs: クリックで選択、同じものを再クリックで unset、別をクリックで replace。
 * - 「現在の画面を自動キャプチャ」 → `captureCurrentViewAsFile` (モック)
 *   が呼ばれ、返ってきた File からサムネが出る。
 * - file input 選択 → サムネが出る。
 * - 削除ボタン → サムネが消える。
 * - 「送信内容をプレビュー →」: 本文ありで活性、空/空白で非活性。
 *   クリック → `feedbackHubApi.submitFeedback` に全フィールドが渡る →
 *   `window.open(returned prefill_url, '_blank')`。
 * - 「キャンセル」 → フォームクリア + `hub.close()`。
 *
 * モック方針:
 *
 * - `$lib/api/feedbackHub` は `vi.mock` でファクトリ差し替え (実 fetch を回避)。
 * - `$lib/utils/screenshotCapture` も同様 (jsdom には canvas 実装がないため html2canvas を直接呼べない)。
 * - `URL.createObjectURL` / `URL.revokeObjectURL` は jsdom 未実装なので
 *   beforeEach で no-op スタブを当てる。
 * - `window.open` は spyOn でモック (実際にタブが開かないように)。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';

// --- Module mocks (vi.mock は import より先に hoist される) -------------------

vi.mock('$lib/api/feedbackHub', () => ({
  feedbackHubApi: {
    submitFeedback: vi.fn(),
    listNotices: vi.fn(),
    unreadCount: vi.fn(),
  },
}));

vi.mock('$lib/utils/screenshotCapture', () => ({
  captureCurrentViewAsFile: vi.fn(),
  captureCurrentView: vi.fn(),
  captureToBase64: vi.fn(),
  captureToBase64Stripped: vi.fn(),
}));

// eslint-disable-next-line import/first
import FeedbackTab from '$lib/components/feedback-hub/FeedbackTab.svelte';
// eslint-disable-next-line import/first
import { feedbackHubApi } from '$lib/api/feedbackHub';
// eslint-disable-next-line import/first
import { captureCurrentViewAsFile } from '$lib/utils/screenshotCapture';
// eslint-disable-next-line import/first
import { createFeedbackHubStore } from '$lib/stores/feedbackHub.svelte';
// eslint-disable-next-line import/first
import { createNoticesStore } from '$lib/stores/notices.svelte';
// eslint-disable-next-line import/first
import { createCrashReportsStore } from '$lib/stores/crashReports.svelte';

// 型ガード付きで取り出した mock fn (テスト本文で `.mockResolvedValue` 等が使える)。
const mockSubmit = vi.mocked(feedbackHubApi.submitFeedback);
const mockCapture = vi.mocked(captureCurrentViewAsFile);

// ---------------------------------------------------------------------------
// テスト共通の helpers
// ---------------------------------------------------------------------------

function makePngFile(name = 'shot.png', body = 'PNGBYTES'): File {
  return new File([body], name, { type: 'image/png' });
}

/**
 * `hub` の DI: グローバル singleton を触らないため、各テスト専用の
 * `createFeedbackHubStore` インスタンスを返す。
 * sub-stores のモック API は空配列で OK (FeedbackTab は notices/crashes を読まない)。
 */
function makeHub() {
  const notices = createNoticesStore({ listNotices: vi.fn().mockResolvedValue([]) } as never);
  const crashes = createCrashReportsStore({
    listPending: vi.fn().mockResolvedValue([]),
    dismiss: vi.fn(),
    markReported: vi.fn(),
  } as never);
  const hub = createFeedbackHubStore(notices, crashes);
  hub.open();
  return hub;
}

// `vi.spyOn(window, 'open')` の戻り値は `MockInstance` の overload union になり、
// svelte-check が `ReturnType<typeof vi.spyOn>` の汎用シグネチャと衝突する。
// 実用上は呼び出し履歴 (mock.calls) しか使わないため、明示的に narrow した型で受ける。
type WindowOpenSpy = {
  mockReturnValue(v: Window | null): WindowOpenSpy;
  mock: { calls: Array<[unknown, unknown, unknown]> };
};
let openSpy: WindowOpenSpy;

beforeEach(() => {
  mockSubmit.mockReset();
  mockCapture.mockReset();
  // happy default: backend が常に prefill_url を返す
  mockSubmit.mockResolvedValue({ prefill_url: 'https://github.com/x/y/issues/new?title=t' });

  // URL.createObjectURL / revokeObjectURL — jsdom 未実装なのでスタブ
  if (typeof URL.createObjectURL !== 'function') {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (URL as any).createObjectURL = vi.fn(() => 'blob:mock-url');
  } else {
    vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:mock-url');
  }
  if (typeof URL.revokeObjectURL !== 'function') {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (URL as any).revokeObjectURL = vi.fn();
  } else {
    vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {});
  }

  openSpy = vi.spyOn(window, 'open').mockReturnValue(null) as unknown as WindowOpenSpy;
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

// ---------------------------------------------------------------------------
// 1. 描画
// ---------------------------------------------------------------------------

describe('FeedbackTab — 描画', () => {
  it('3 種別チップ + textarea + Thumbs + スクショカード + フッタ 2 ボタンが出る', () => {
    render(FeedbackTab, { hub: makeHub() });

    // 種別チップ (role="radio" — adversarial-review fix で radiogroup パターンへ移行)
    expect(screen.getByRole('radio', { name: /機能要望/ })).toBeDefined();
    expect(screen.getByRole('radio', { name: /使いにくさ/ })).toBeDefined();
    expect(screen.getByRole('radio', { name: /^感想$/ })).toBeDefined();

    // textarea
    expect(screen.getByTestId('feedback-body')).toBeDefined();

    // Thumbs 3 個 (aria-label)
    expect(screen.getByLabelText('よかった')).toBeDefined();
    expect(screen.getByLabelText('ふつう')).toBeDefined();
    expect(screen.getByLabelText('いまいち')).toBeDefined();

    // スクショカード
    expect(screen.getByTestId('screenshot-card')).toBeDefined();
    expect(screen.getByTestId('screenshot-select')).toBeDefined();
    expect(screen.getByTestId('screenshot-auto')).toBeDefined();

    // フッタ
    expect(screen.getByTestId('feedback-cancel')).toBeDefined();
    expect(screen.getByTestId('feedback-submit')).toBeDefined();
  });

  it('初期状態では「機能要望」チップが active', () => {
    render(FeedbackTab, { hub: makeHub() });
    const feature = screen.getByRole('radio', { name: /機能要望/ });
    expect(feature.getAttribute('aria-checked')).toBe('true');
  });

  it('初期 placeholder は feature 用の例文', () => {
    render(FeedbackTab, { hub: makeHub() });
    const ta = screen.getByTestId('feedback-body') as HTMLTextAreaElement;
    expect(ta.placeholder).toMatch(/テンプレートを選べると便利/);
  });
});

// ---------------------------------------------------------------------------
// 1b. 種別チップ ARIA (radiogroup / radio / aria-checked)
// ---------------------------------------------------------------------------

describe('FeedbackTab — 種別チップ ARIA (radiogroup pattern)', () => {
  // Adversarial-review finding: kind chips were `<fieldset>` + `<button
  // aria-pressed>` (= a toggle-button group). But exactly-one selection is
  // required and a default value is always set → the correct ARIA pattern is
  // `radiogroup` + `role="radio" aria-checked`. Screen-readers announce
  // radiogroups as "one of N" instead of "press to toggle", matching the
  // intended semantics. This block locks the new pattern in place.
  it('種別チップ群は role="radiogroup" + aria-label="種別" でラップされる', () => {
    render(FeedbackTab, { hub: makeHub() });
    const group = screen.getByRole('radiogroup', { name: '種別' });
    expect(group).toBeDefined();
  });

  it('種別チップは role="radio" を持ち、選択中だけ aria-checked="true"', () => {
    render(FeedbackTab, { hub: makeHub() });
    const radios = screen.getAllByRole('radio');
    expect(radios).toHaveLength(3);
    const feature = screen.getByRole('radio', { name: /機能要望/ });
    const complaint = screen.getByRole('radio', { name: /使いにくさ/ });
    const impression = screen.getByRole('radio', { name: /^感想$/ });
    expect(feature.getAttribute('aria-checked')).toBe('true');
    expect(complaint.getAttribute('aria-checked')).toBe('false');
    expect(impression.getAttribute('aria-checked')).toBe('false');
  });

  it('別のチップをクリックすると aria-checked が切り替わる (radio 一択)', async () => {
    render(FeedbackTab, { hub: makeHub() });
    const feature = screen.getByRole('radio', { name: /機能要望/ });
    const complaint = screen.getByRole('radio', { name: /使いにくさ/ });
    await fireEvent.click(complaint);
    expect(complaint.getAttribute('aria-checked')).toBe('true');
    expect(feature.getAttribute('aria-checked')).toBe('false');
  });
});

// ---------------------------------------------------------------------------
// 2. 種別チップ → placeholder 切替
// ---------------------------------------------------------------------------

describe('FeedbackTab — 種別チップ', () => {
  it('「使いにくさ」クリックで aria-checked が切り替わる', async () => {
    render(FeedbackTab, { hub: makeHub() });
    const feature = screen.getByRole('radio', { name: /機能要望/ });
    const complaint = screen.getByRole('radio', { name: /使いにくさ/ });
    expect(feature.getAttribute('aria-checked')).toBe('true');

    await fireEvent.click(complaint);
    expect(complaint.getAttribute('aria-checked')).toBe('true');
    expect(feature.getAttribute('aria-checked')).toBe('false');
  });

  it('「使いにくさ」選択で placeholder が complaint 用に切り替わる', async () => {
    render(FeedbackTab, { hub: makeHub() });
    await fireEvent.click(screen.getByRole('radio', { name: /使いにくさ/ }));
    const ta = screen.getByTestId('feedback-body') as HTMLTextAreaElement;
    expect(ta.placeholder).toMatch(/具体的に教えてください/);
  });

  it('「感想」選択で placeholder が impression 用に切り替わる', async () => {
    render(FeedbackTab, { hub: makeHub() });
    await fireEvent.click(screen.getByRole('radio', { name: /^感想$/ }));
    const ta = screen.getByTestId('feedback-body') as HTMLTextAreaElement;
    expect(ta.placeholder).toMatch(/感想を自由に/);
  });
});

// ---------------------------------------------------------------------------
// 3. 本文入力
// ---------------------------------------------------------------------------

describe('FeedbackTab — 本文', () => {
  it('textarea に入力すると value に反映される', async () => {
    render(FeedbackTab, { hub: makeHub() });
    const ta = screen.getByTestId('feedback-body') as HTMLTextAreaElement;
    await fireEvent.input(ta, { target: { value: '改善希望: ダークモード' } });
    expect(ta.value).toBe('改善希望: ダークモード');
  });
});

// ---------------------------------------------------------------------------
// 4. Thumbs (sentiment)
// ---------------------------------------------------------------------------

describe('FeedbackTab — Thumbs', () => {
  it('初期はどれも非選択 (aria-pressed=false)', () => {
    render(FeedbackTab, { hub: makeHub() });
    expect(screen.getByLabelText('よかった').getAttribute('aria-pressed')).toBe('false');
    expect(screen.getByLabelText('ふつう').getAttribute('aria-pressed')).toBe('false');
    expect(screen.getByLabelText('いまいち').getAttribute('aria-pressed')).toBe('false');
  });

  it('ThumbsUp クリックで sentiment=up になる (aria-pressed=true)', async () => {
    render(FeedbackTab, { hub: makeHub() });
    const up = screen.getByLabelText('よかった');
    await fireEvent.click(up);
    expect(up.getAttribute('aria-pressed')).toBe('true');
  });

  it('同じボタンを再クリックすると sentiment が unset される (toggle off)', async () => {
    render(FeedbackTab, { hub: makeHub() });
    const up = screen.getByLabelText('よかった');
    await fireEvent.click(up);
    expect(up.getAttribute('aria-pressed')).toBe('true');
    await fireEvent.click(up);
    expect(up.getAttribute('aria-pressed')).toBe('false');
  });

  it('別ボタンをクリックすると replace される (Up→Down で Up が外れ Down が active)', async () => {
    render(FeedbackTab, { hub: makeHub() });
    const up = screen.getByLabelText('よかった');
    const down = screen.getByLabelText('いまいち');
    await fireEvent.click(up);
    await fireEvent.click(down);
    expect(up.getAttribute('aria-pressed')).toBe('false');
    expect(down.getAttribute('aria-pressed')).toBe('true');
  });
});

// ---------------------------------------------------------------------------
// 5. スクショ
// ---------------------------------------------------------------------------

describe('FeedbackTab — スクショ', () => {
  it('「現在の画面を自動キャプチャ」 → captureCurrentViewAsFile が呼ばれサムネ表示', async () => {
    mockCapture.mockResolvedValue(makePngFile('auto.png'));
    render(FeedbackTab, { hub: makeHub() });

    await fireEvent.click(screen.getByTestId('screenshot-auto'));
    await waitFor(() => expect(mockCapture).toHaveBeenCalledTimes(1));

    // サムネ表示 (img の alt と remove ボタンの存在で確認)
    await waitFor(() => {
      expect(screen.getByAltText('添付スクリーンショット')).toBeDefined();
    });
    expect(screen.getByTestId('screenshot-remove')).toBeDefined();
  });

  it('file input change イベントで選んだファイルがサムネ表示される', async () => {
    render(FeedbackTab, { hub: makeHub() });
    const input = screen.getByTestId('screenshot-input') as HTMLInputElement;
    const file = makePngFile('user-picked.png');

    // jsdom: input.files に File を入れる
    Object.defineProperty(input, 'files', { value: [file], configurable: true });
    await fireEvent.change(input);

    await waitFor(() => {
      expect(screen.getByAltText('添付スクリーンショット')).toBeDefined();
    });
  });

  it('「削除」ボタンでサムネが消え、選択 UI に戻る', async () => {
    mockCapture.mockResolvedValue(makePngFile('to-delete.png'));
    render(FeedbackTab, { hub: makeHub() });

    await fireEvent.click(screen.getByTestId('screenshot-auto'));
    await waitFor(() => expect(screen.getByTestId('screenshot-remove')).toBeDefined());

    await fireEvent.click(screen.getByTestId('screenshot-remove'));

    await waitFor(() => {
      expect(screen.queryByTestId('screenshot-remove')).toBeNull();
    });
    // 選択 UI が戻ってきていること
    expect(screen.getByTestId('screenshot-select')).toBeDefined();
    expect(screen.getByTestId('screenshot-auto')).toBeDefined();
  });

  it('非画像ファイルを drop するとエラー文言「画像ファイルのみ添付できます」が出る', async () => {
    // Adversarial-review finding: handleDrop returned silently for non-image
    // files, so users got zero feedback when they accidentally dropped a .txt /
    // .pdf onto the screenshot card. Spec §5.5.4 expects affordance-level
    // feedback. Surface a visible error.
    render(FeedbackTab, { hub: makeHub() });
    const card = screen.getByTestId('screenshot-card');
    const textFile = new File(['hello'], 'note.txt', { type: 'text/plain' });
    // jsdom's DragEvent doesn't carry a real dataTransfer; build one manually.
    const dropEvent = new Event('drop', { bubbles: true, cancelable: true });
    Object.defineProperty(dropEvent, 'dataTransfer', {
      value: { files: [textFile] },
      configurable: true,
    });
    card.dispatchEvent(dropEvent);
    await waitFor(() => {
      expect(screen.getByText('画像ファイルのみ添付できます')).toBeDefined();
    });
    // サムネは出ない (= setScreenshot は呼ばれていない)
    expect(screen.queryByAltText('添付スクリーンショット')).toBeNull();
  });

  it('自動キャプチャが reject されてもクラッシュせずエラー文言を出す', async () => {
    mockCapture.mockRejectedValueOnce(new Error('canvas tainted'));
    render(FeedbackTab, { hub: makeHub() });

    await fireEvent.click(screen.getByTestId('screenshot-auto'));
    await waitFor(() => {
      expect(screen.getByText(/スクリーンショットの取得に失敗/)).toBeDefined();
    });
  });
});

// ---------------------------------------------------------------------------
// 6. 送信 (submit)
// ---------------------------------------------------------------------------

describe('FeedbackTab — 送信内容をプレビュー', () => {
  it('body が空のとき送信ボタンは disabled', () => {
    render(FeedbackTab, { hub: makeHub() });
    const submit = screen.getByTestId('feedback-submit') as HTMLButtonElement;
    expect(submit.disabled).toBe(true);
  });

  it('body が空白のみのとき送信ボタンは disabled', async () => {
    render(FeedbackTab, { hub: makeHub() });
    const ta = screen.getByTestId('feedback-body') as HTMLTextAreaElement;
    await fireEvent.input(ta, { target: { value: '   \n\t  ' } });
    const submit = screen.getByTestId('feedback-submit') as HTMLButtonElement;
    expect(submit.disabled).toBe(true);
  });

  it('body 入力で送信ボタンが活性化する', async () => {
    render(FeedbackTab, { hub: makeHub() });
    const ta = screen.getByTestId('feedback-body') as HTMLTextAreaElement;
    await fireEvent.input(ta, { target: { value: 'よくなった!' } });
    const submit = screen.getByTestId('feedback-submit') as HTMLButtonElement;
    await waitFor(() => expect(submit.disabled).toBe(false));
  });

  it('送信クリックで submitFeedback に kind/body/sentiment が渡り window.open が呼ばれる', async () => {
    mockSubmit.mockResolvedValue({ prefill_url: 'https://gh/issues/new?title=OK' });
    render(FeedbackTab, { hub: makeHub() });

    // 種別: complaint, body: text, sentiment: up
    await fireEvent.click(screen.getByRole('radio', { name: /使いにくさ/ }));
    await fireEvent.input(screen.getByTestId('feedback-body'), {
      target: { value: '設定画面が見つけにくい' },
    });
    await fireEvent.click(screen.getByLabelText('よかった'));

    await fireEvent.click(screen.getByTestId('feedback-submit'));

    await waitFor(() => expect(mockSubmit).toHaveBeenCalledTimes(1));
    const payload = mockSubmit.mock.calls[0][0];
    expect(payload.kind).toBe('complaint');
    expect(payload.body).toBe('設定画面が見つけにくい');
    expect(payload.sentiment).toBe('up');
    // screenshot は未添付なので null
    expect(payload.screenshot_b64).toBeNull();

    await waitFor(() => expect(openSpy).toHaveBeenCalledTimes(1));
    expect(openSpy.mock.calls[0][0]).toBe('https://gh/issues/new?title=OK');
    expect(openSpy.mock.calls[0][1]).toBe('_blank');
  });

  it('スクショ添付ありで送信すると screenshot_b64 (bare base64) が同梱される', async () => {
    mockSubmit.mockResolvedValue({ prefill_url: 'https://gh/issues/new' });
    mockCapture.mockResolvedValue(makePngFile('shot.png', 'BINARYPNG'));
    render(FeedbackTab, { hub: makeHub() });

    await fireEvent.input(screen.getByTestId('feedback-body'), {
      target: { value: 'スクショ付きフィードバック' },
    });
    await fireEvent.click(screen.getByTestId('screenshot-auto'));
    await waitFor(() => expect(screen.getByTestId('screenshot-remove')).toBeDefined());

    await fireEvent.click(screen.getByTestId('feedback-submit'));

    await waitFor(() => expect(mockSubmit).toHaveBeenCalledTimes(1));
    const payload = mockSubmit.mock.calls[0][0];
    expect(typeof payload.screenshot_b64).toBe('string');
    // bare base64: data URL の prefix が剥がれていること
    expect(payload.screenshot_b64?.startsWith('data:')).toBe(false);
    expect((payload.screenshot_b64 ?? '').length).toBeGreaterThan(0);
  });

  it('送信失敗時はエラー文言を出し、window.open は呼ばれない', async () => {
    mockSubmit.mockRejectedValueOnce(new Error('500 boom'));
    render(FeedbackTab, { hub: makeHub() });

    await fireEvent.input(screen.getByTestId('feedback-body'), {
      target: { value: '失敗テスト' },
    });
    await fireEvent.click(screen.getByTestId('feedback-submit'));

    await waitFor(() => expect(screen.getByText(/500 boom/)).toBeDefined());
    expect(openSpy).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// 7. キャンセル
// ---------------------------------------------------------------------------

describe('FeedbackTab — キャンセル', () => {
  it('「キャンセル」クリックでフォームがクリアされ hub.close() が呼ばれる', async () => {
    const hub = makeHub();
    expect(hub.drawerOpen).toBe(true);

    render(FeedbackTab, { hub });

    // フォームに入力
    await fireEvent.click(screen.getByRole('radio', { name: /使いにくさ/ }));
    await fireEvent.input(screen.getByTestId('feedback-body'), {
      target: { value: '消えてほしい本文' },
    });
    await fireEvent.click(screen.getByLabelText('いまいち'));

    // キャンセル
    await fireEvent.click(screen.getByTestId('feedback-cancel'));

    // drawer が閉じている
    expect(hub.drawerOpen).toBe(false);

    // フォームが初期化されていること (kind=feature / body='' / sentiment=null)
    // キャンセル後 drawer は close するが component はテスト内では unmount しないので
    // 内部 state を DOM 経由で覗ける。
    const ta = screen.getByTestId('feedback-body') as HTMLTextAreaElement;
    expect(ta.value).toBe('');
    expect(
      screen.getByRole('radio', { name: /機能要望/ }).getAttribute('aria-checked'),
    ).toBe('true');
    expect(screen.getByLabelText('いまいち').getAttribute('aria-pressed')).toBe('false');
  });
});
