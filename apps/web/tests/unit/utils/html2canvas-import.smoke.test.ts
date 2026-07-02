import { describe, it, expect } from 'vitest';

/**
 * Smoke test: ensure html2canvas resolves and imports as an ES module.
 *
 * html2canvas requires real canvas/DOM APIs at *runtime*, so we don't render
 * anything here — we just check the package is installed and importable.
 * If the dependency is missing or its package exports are broken, this test
 * fails before any feature code that depends on it runs.
 */
describe('html2canvas import smoke test', () => {
	it('loads html2canvas as a callable default export', async () => {
		const mod = await import('html2canvas');
		const html2canvas = mod.default ?? mod;
		expect(typeof html2canvas).toBe('function');
	});
});
