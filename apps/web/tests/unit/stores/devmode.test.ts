/**
 * devmode ストア: ロゴ 7 連打 / 3 秒の隠しコマンドと強制リセット(spec §5 / §10.1)。
 */
import { beforeEach, describe, expect, it } from 'vitest';

const { devmode } = await import('$lib/stores/devmode.svelte');

beforeEach(() => {
  devmode.syncEnabled(false); // リセット(OFF遷移でunlocked/panelOpenが消える)
  localStorage.clear();
});

describe('devmode hidden command', () => {
  it('設定OFFの間はロゴ連打しても何も起きない', () => {
    for (let i = 0; i < 10; i++) devmode.registerLogoClick(1000 + i * 10);
    expect(devmode.unlocked).toBe(false);
    expect(devmode.panelOpen).toBe(false);
  });

  it('設定ON + 3秒以内に7クリックでパネルが開く', () => {
    devmode.syncEnabled(true);
    for (let i = 0; i < 7; i++) devmode.registerLogoClick(1000 + i * 100);
    expect(devmode.unlocked).toBe(true);
    expect(devmode.panelOpen).toBe(true);
    expect(localStorage.getItem('nb-ollama-devmode-unlocked')).toBe('true');
  });

  it('3秒を超えて分散した7クリックでは開かない', () => {
    devmode.syncEnabled(true);
    for (let i = 0; i < 7; i++) devmode.registerLogoClick(1000 + i * 600); // 幅3.6s
    expect(devmode.panelOpen).toBe(false);
  });

  it('設定OFFへ遷移するとunlocked/panelOpenが強制リセットされる', () => {
    devmode.syncEnabled(true);
    for (let i = 0; i < 7; i++) devmode.registerLogoClick(1000 + i * 100);
    expect(devmode.panelOpen).toBe(true);

    devmode.syncEnabled(false);
    expect(devmode.unlocked).toBe(false);
    expect(devmode.panelOpen).toBe(false);
    expect(localStorage.getItem('nb-ollama-devmode-unlocked')).toBeNull();
  });

  it('forceReset(403/shutdown受信)でも同様にリセットされる', () => {
    devmode.syncEnabled(true);
    for (let i = 0; i < 7; i++) devmode.registerLogoClick(1000 + i * 100);
    devmode.forceReset();
    expect(devmode.unlocked).toBe(false);
    expect(devmode.panelOpen).toBe(false);
  });
});
