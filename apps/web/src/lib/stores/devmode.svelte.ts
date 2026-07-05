/**
 * 開発者モードの状態と隠しコマンド(spec 2026-07-02 §5 / §10.1)。
 *
 * - enabled:  設定(BE 永続)由来。settingsStore.load 後に sync する
 * - unlocked: ロゴ 7 回 / 3 秒以内クリックで true。localStorage に保存
 * - panelOpen: Dev パネルの表示状態
 *
 * enabled が false の間はロゴ連打を無視し、false へ遷移した瞬間に
 * unlocked / panelOpen を強制リセットして localStorage も消す。
 * /api/dev/* が 403 を返した場合も同じリセットを行う。
 */

const LS_KEY = 'nb-ollama-devmode-unlocked';
const CLICK_WINDOW_MS = 3000;
const CLICK_THRESHOLD = 7;

function createDevmodeStore() {
  let enabled = $state(false);
  let unlocked = $state(false);
  let panelOpen = $state(false);
  let clicks: number[] = [];

  try {
    unlocked = localStorage.getItem(LS_KEY) === 'true';
  } catch {
    /* SSR / プライベートモードでは無視 */
  }

  function resetHidden() {
    unlocked = false;
    panelOpen = false;
    clicks = [];
    try {
      localStorage.removeItem(LS_KEY);
    } catch {
      /* noop */
    }
  }

  return {
    get enabled() {
      return enabled;
    },
    get unlocked() {
      return unlocked;
    },
    get panelOpen() {
      return panelOpen;
    },

    /** settingsStore.load 後に BE の設定値を反映する。OFF 遷移で強制リセット。 */
    syncEnabled(next: boolean) {
      const was = enabled;
      enabled = next;
      if (was && !next) resetHidden();
      if (!next) clicks = [];
    },

    /** サイドバーロゴのクリックを登録する(spec FR-2)。 */
    registerLogoClick(now: number = Date.now()) {
      if (!enabled) {
        clicks = [];
        return;
      }
      clicks = [...clicks.filter((t) => now - t < CLICK_WINDOW_MS), now];
      if (clicks.length >= CLICK_THRESHOLD) {
        clicks = [];
        unlocked = true;
        panelOpen = true;
        try {
          localStorage.setItem(LS_KEY, 'true');
        } catch {
          /* noop */
        }
      }
    },

    openPanel() {
      if (enabled && unlocked) panelOpen = true;
    },
    closePanel() {
      panelOpen = false;
    },

    /** 403 / shutdown 受信時のリセット(spec §10.1)。 */
    forceReset() {
      resetHidden();
    },
  };
}

export const devmode = createDevmodeStore();
