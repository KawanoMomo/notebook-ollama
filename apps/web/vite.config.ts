import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

// VITE_API_TARGET でプロキシ先を上書きできるようにする(代替ポート上の dev BE 向け)。
const API_TARGET = process.env.VITE_API_TARGET ?? 'http://localhost:8765';

export default defineConfig({
  plugins: [sveltekit()],
  server: {
    port: 5173,
    proxy: {
      '/api': API_TARGET,
      '/mcp': API_TARGET,
      '/ws': {
        target: API_TARGET,
        ws: true,
      },
    },
  },
});
