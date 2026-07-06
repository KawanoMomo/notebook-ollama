import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createPttKeyTracker, type PttEvent } from '$lib/audio/pttKey';

function keyEvent(over: Partial<KeyboardEvent> = {}): KeyboardEvent {
  return {
    code: 'Space',
    repeat: false,
    isComposing: false,
    ctrlKey: false,
    altKey: false,
    metaKey: false,
    shiftKey: false,
    ...over,
  } as KeyboardEvent;
}

describe('createPttKeyTracker', () => {
  let events: PttEvent[];
  let tracker: ReturnType<typeof createPttKeyTracker>;

  beforeEach(() => {
    vi.useFakeTimers();
    events = [];
    tracker = createPttKeyTracker({ code: 'Space', onEvent: (e) => events.push(e) });
  });
  afterEach(() => vi.useRealTimers());

  it('250ms 未満の解放は tap(pressStart → tap)', () => {
    expect(tracker.handleKeydown(keyEvent())).toBe(true);
    vi.advanceTimersByTime(100);
    expect(tracker.handleKeyup(keyEvent())).toBe(true);
    expect(events.map((e) => e.type)).toEqual(['pressStart', 'tap']);
  });

  it('250ms 以上の保持は holdStart → holdEnd', () => {
    tracker.handleKeydown(keyEvent());
    vi.advanceTimersByTime(300);
    tracker.handleKeyup(keyEvent());
    expect(events.map((e) => e.type)).toEqual(['pressStart', 'holdStart', 'holdEnd']);
  });

  it('押下中の同一キー repeat は消費する(true)が状態は変えない', () => {
    tracker.handleKeydown(keyEvent());
    expect(tracker.handleKeydown(keyEvent({ repeat: true }))).toBe(true);
    vi.advanceTimersByTime(300);
    tracker.handleKeyup(keyEvent());
    expect(events.map((e) => e.type)).toEqual(['pressStart', 'holdStart', 'holdEnd']);
    expect(events.filter((e) => e.type === 'pressStart')).toHaveLength(1);
  });

  it('未押下時の repeat は不介入(false)', () => {
    expect(tracker.handleKeydown(keyEvent({ repeat: true }))).toBe(false);
    expect(events).toHaveLength(0);
  });

  it('IME 変換中(isComposing)は不介入', () => {
    expect(tracker.handleKeydown(keyEvent({ isComposing: true }))).toBe(false);
    expect(events).toHaveLength(0);
  });

  it('修飾キー同時押しは不介入', () => {
    expect(tracker.handleKeydown(keyEvent({ ctrlKey: true }))).toBe(false);
    expect(events).toHaveLength(0);
  });

  it('code 不一致は不介入', () => {
    expect(tracker.handleKeydown(keyEvent({ code: 'KeyA' }))).toBe(false);
    expect(events).toHaveLength(0);
  });

  it('押下していない状態の keyup は無視', () => {
    expect(tracker.handleKeyup(keyEvent())).toBe(false);
    expect(events).toHaveLength(0);
  });

  it('cancel() は保留中の状態を破棄する(holdStart 前)', () => {
    tracker.handleKeydown(keyEvent());
    tracker.cancel();
    vi.advanceTimersByTime(300);
    expect(events.map((e) => e.type)).toEqual(['pressStart']);
    // cancel 後の keyup はイベントを出さない
    expect(tracker.handleKeyup(keyEvent())).toBe(false);
  });
});
