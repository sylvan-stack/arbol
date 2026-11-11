import { resolve } from 'node:path';
import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';
const shared = process.env.ARBOL_SHARED_ELMA_RENDERER === '1';
const legacyBackendBuild = shared
  ? 'undefined'
  : JSON.stringify(process.env.ARBOL_BUILD_NUMBER || 'development');

export default defineConfig({
  plugins: [svelte()],
  base: './',
  build: {
    outDir: 'dist',
    target: 'es2022',
    ...(shared && {
      rolldownOptions: {
        input: { elma: resolve('index.html'), seqoya: resolve('seqoya.html') },
      },
    }),
  },
  define: { __ARBOL_BUILD__: legacyBackendBuild },
});
