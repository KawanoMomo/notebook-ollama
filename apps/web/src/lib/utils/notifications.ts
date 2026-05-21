let permissionRequested = false;

export function notificationsSupported(): boolean {
  return typeof window !== "undefined" && "Notification" in window;
}

export async function requestPermissionOnce(): Promise<void> {
  if (!notificationsSupported() || permissionRequested) return;
  permissionRequested = true;
  if (Notification.permission === "default") {
    try {
      await Notification.requestPermission();
    } catch {
      // user agent may reject silently
    }
  }
}

function shouldShow(): boolean {
  if (!notificationsSupported()) return false;
  if (Notification.permission !== "granted") return false;
  return document.visibilityState === "hidden" || !document.hasFocus();
}

export function notify(opts: { title: string; body: string; tag?: string }): void {
  if (!shouldShow()) return;
  try {
    const n = new Notification(opts.title, { body: opts.body, tag: opts.tag });
    n.onclick = () => {
      window.focus();
      n.close();
    };
  } catch {
    // Notification constructor can throw in some sandboxed contexts
  }
}
