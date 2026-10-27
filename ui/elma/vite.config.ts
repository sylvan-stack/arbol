import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';
export default defineConfig({plugins:[svelte()],base:'./',build:{outDir:'dist',target:'es2022'},define:{__ARBOL_BUILD__:JSON.stringify(process.env.ARBOL_BUILD_NUMBER || 'development')}});
