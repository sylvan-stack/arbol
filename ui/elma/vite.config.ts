import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';
const legacyBackendBuild = process.env.ARBOL_SHARED_ELMA_RENDERER === '1'
  ? 'undefined'
  : JSON.stringify(process.env.ARBOL_BUILD_NUMBER || 'development');

export default defineConfig({
  plugins: [svelte()],
  base: './',
  build: { outDir: 'dist', target: 'es2022' },
  define: { __ARBOL_BUILD__: legacyBackendBuild },
});
