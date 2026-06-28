export interface NavMemoryStore {
  readonly lastPath: string;
  record(path: string): void;
}

export function createNavMemoryStore(): NavMemoryStore {
  let lastPath = $state('/');

  return {
    get lastPath() {
      return lastPath;
    },
    record(path: string) {
      // 設定ページ自身は記録しない（設定→設定の自己参照／無限ループを防ぐ）。
      if (path.startsWith('/settings')) return;
      lastPath = path;
    },
  };
}

export const navMemoryStore = createNavMemoryStore();
