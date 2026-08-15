import { describe, expect, it } from 'vitest';
import {
  DEFAULT_VIEWER_WIDTH,
  MIN_VIEWER_WIDTH,
  clampViewerWidth,
} from '../../src/lib/utils/viewerWidth';

describe('clampViewerWidth', () => {
  it('下限より狭くしない', () => {
    expect(clampViewerWidth(50, 1600)).toBe(MIN_VIEWER_WIDTH);
  });

  it('ウィンドウ幅の7割を超えない(チャット側が潰れない)', () => {
    expect(clampViewerWidth(9999, 1000)).toBe(700);
  });

  it('通常の値はそのまま通す', () => {
    expect(clampViewerWidth(520, 1600)).toBe(520);
  });

  it('狭いウィンドウでも下限を優先する', () => {
    expect(clampViewerWidth(300, 300)).toBe(MIN_VIEWER_WIDTH);
  });

  it('NaN は既定値へ倒す', () => {
    expect(clampViewerWidth(Number.NaN, 1600)).toBe(DEFAULT_VIEWER_WIDTH);
  });
});
