import { defineConfig } from 'vite';
import { resolve } from 'path';
import { createAliases } from './build-aliases.mjs';

export default defineConfig({
  root: '.',
  publicDir: false,
  build: {
    outDir: 'static/js/build',
    sourcemap: true,
    emptyOutDir: true,
    target: 'es2020',
    minify: false,
    rollupOptions: {
      input: resolve(__dirname, 'src/bundles/app.ts'),
      output: {
        format: 'iife',
        entryFileNames: 'app-bundle.js',
      },
    },
  },
  resolve: {
    alias: createAliases(__dirname),
  },
});
