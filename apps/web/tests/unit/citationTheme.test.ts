import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

/**
 * Vite は `new URL('...', import.meta.url)` をアセット URL 解決として書き換えるため、
 * vitest 上では `http://localhost:3000/src/app.css` になり readFileSync に渡せない
 * ("The URL must be of scheme file")。ファイル実体を読むので明示的にパスへ落とす。
 */
const here = dirname(fileURLToPath(import.meta.url));
const readSrc = (rel: string) => readFileSync(resolve(here, '../../src', rel), 'utf8');

const css = readSrc('app.css');

describe('配色トークン', () => {
  it('黄色の引用トークンは廃止されている', () => {
    expect(css).not.toContain('--color-citation-bg');
    expect(css).not.toContain('--color-citation-border');
    expect(css).not.toContain('#fff8c4');
  });

  it('根拠用トークンが定義されている', () => {
    expect(css).toContain('--color-evidence:');
    expect(css).toContain('--color-evidence-soft:');
    expect(css).toContain('--color-evidence-faint:');
  });
});

describe('旧トークンの参照が残っていない', () => {
  it('SourceViewer が廃止トークンを参照していない', () => {
    const sv = readSrc('lib/components/SourceViewer.svelte');
    expect(sv).not.toContain('--color-citation-');
  });

  it('ChatMessage が廃止トークンを参照していない', () => {
    const cm = readSrc('lib/components/ChatMessage.svelte');
    expect(cm).not.toContain('--color-citation-');
  });
});
