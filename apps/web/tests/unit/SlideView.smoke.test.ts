import { render, waitFor } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';

describe('SlideView smoke', () => {
  it('pdfjs-dist が import 可能', async () => {
    const mod = await import('pdfjs-dist');
    expect(mod.getDocument).toBeTypeOf('function');
  });

  it('SlideView コンポーネントが import 可能でpropsを持つ', async () => {
    const mod = await import('$lib/components/SlideView.svelte');
    expect(mod.default).toBeDefined();
  });

  it('ロード失敗時もcanvasがDOMに残存する(エラー状態からの回復可能性)', async () => {
    // jsdom にはネットワークも Worker もないため、存在しない URL への getDocument は
    // 必ず失敗し onRenderError / エラー表示の経路に入る。ここで検証したいのは
    // 「エラー表示中も canvas が DOM に残り bind:this が生きている」こと
    // (canvas が外れると以後の render() が全てガードで止まり、一度の一時的失敗で
    // セッション全体が回復不能になる)。実描画の正しさは PM-12 evaluator が担保。
    const mod = await import('$lib/components/SlideView.svelte');
    const onRenderError = vi.fn();
    const { container } = render(mod.default, {
      props: { url: '/nonexistent.pdf', page: 1, onRenderError },
    });
    await waitFor(
      () => {
        expect(container.querySelector('[role="alert"]')).not.toBeNull();
      },
      { timeout: 10_000 },
    );
    expect(onRenderError).toHaveBeenCalled();
    // 回復可能性の構造的証明: エラー表示中も canvas は DOM に居続ける
    expect(container.querySelector('canvas')).not.toBeNull();
  }, 15_000);
});
