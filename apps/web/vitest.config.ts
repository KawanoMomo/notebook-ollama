import { defineConfig } from 'vitest/config';
import { svelte } from '@sveltejs/vite-plugin-svelte';
import { svelteTesting } from '@testing-library/svelte/vite';
import { fileURLToPath, URL } from 'node:url';

export default defineConfig({
  plugins: [svelte({ hot: false }), svelteTesting()],
  resolve: {
    alias: {
      $lib: fileURLToPath(new URL('./src/lib', import.meta.url)),
      // SvelteKit's `$app/navigation` is a virtual module created by
      // `svelte-kit sync` at dev/build time. Unit tests don't run through
      // SvelteKit, so we redirect it to a thin stub. Individual tests can
      // still `vi.mock('$app/navigation', ...)` to override.
      '$app/navigation': fileURLToPath(
        new URL('./tests/stubs/app-navigation.ts', import.meta.url),
      ),
    },
  },
  test: {
    environment: 'jsdom',
    include: ['tests/unit/**/*.test.ts'],
    globals: true,
    setupFiles: ['./vitest.setup.ts'],
  },
});
