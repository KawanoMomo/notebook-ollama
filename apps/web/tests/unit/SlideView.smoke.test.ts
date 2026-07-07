import { describe, expect, it } from 'vitest';

describe('SlideView smoke', () => {
  it('pdfjs-dist が import 可能', async () => {
    const mod = await import('pdfjs-dist');
    expect(mod.getDocument).toBeTypeOf('function');
  });

  it('SlideView コンポーネントが import 可能でpropsを持つ', async () => {
    const mod = await import('$lib/components/SlideView.svelte');
    expect(mod.default).toBeDefined();
  });
});
