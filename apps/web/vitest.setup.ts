/**
 * Vitest setup — runs once before all unit-test files.
 *
 * Polyfills Web Animations API methods that jsdom does not implement.
 * Svelte 5 transitions (`fly`, `fade`, ...) compile to `Element.animate()`,
 * which throws `TypeError: element.animate is not a function` in jsdom.
 * We stub it with a minimal no-op `Animation`-like object so the transition
 * pipeline can call `.finished`, `.cancel()`, `.commitStyles()` without throwing.
 */

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
