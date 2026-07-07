/**
 * Vitest setup — runs once before all unit-test files.
 *
 * Polyfills Web Animations API methods that jsdom does not implement.
 * Svelte 5 transitions (`fly`, `fade`, ...) compile to `Element.animate()`,
 * which throws `TypeError: element.animate is not a function` in jsdom.
 * We stub it with a minimal no-op `Animation`-like object so the transition
 * pipeline can call `.finished`, `.cancel()`, `.commitStyles()` without throwing.
 */

/**
 * Minimal DOMMatrix polyfill.
 *
 * jsdom does not implement the CSS Geometry Interfaces (DOMMatrix/DOMPoint/DOMRect).
 * pdfjs-dist (SlideView.svelte's dependency) evaluates `const SCALE_MATRIX = new DOMMatrix();`
 * at module top-level, so merely `import('pdfjs-dist')` throws `DOMMatrix is not defined`
 * under jsdom — before any actual canvas rendering is attempted. Real PDF rendering is not
 * exercised in jsdom (see SlideView.smoke.test.ts); this stub exists only so the module can
 * be imported and its exports asserted on.
 */
if (typeof globalThis.DOMMatrix === 'undefined') {
  class DOMMatrixPolyfill {
    a = 1;
    b = 0;
    c = 0;
    d = 1;
    e = 0;
    f = 0;
    constructor(init?: string | number[]) {
      if (Array.isArray(init) && init.length >= 6) {
        [this.a, this.b, this.c, this.d, this.e, this.f] = init;
      }
    }
  }
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  (globalThis as any).DOMMatrix = DOMMatrixPolyfill;
}

/**
 * Minimal ResizeObserver stub.
 *
 * jsdom does not implement ResizeObserver, and jsdom never performs layout, so
 * resize callbacks would never fire anyway. SlideView.svelte observes its
 * container to re-render the PDF page on size changes; in unit tests we only
 * need mounting/unmounting not to throw.
 */
if (typeof globalThis.ResizeObserver === 'undefined') {
  class ResizeObserverStub {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  (globalThis as any).ResizeObserver = ResizeObserverStub;
}

if (typeof Element !== 'undefined' && !Element.prototype.animate) {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  (Element.prototype as any).animate = function animate(): Animation {
    const finished = Promise.resolve(undefined as unknown as Animation);
    const fake = {
      cancel() {},
      finish() {},
      pause() {},
      play() {},
      reverse() {},
      commitStyles() {},
      persist() {},
      updatePlaybackRate() {},
      addEventListener() {},
      removeEventListener() {},
      currentTime: 0,
      playbackRate: 1,
      playState: 'finished' as AnimationPlayState,
      finished,
      ready: finished,
      onfinish: null,
      oncancel: null,
      onremove: null,
    };
    return fake as unknown as Animation;
  };
}
