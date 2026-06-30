import { defineConfig } from 'vite';
import { resolve } from 'path';

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
    alias: {
      '@workspace': resolve(__dirname, 'src/workspace'),
      '@chat': resolve(__dirname, 'src/chat'),
      '@skills': resolve(__dirname, 'src/skills'),
      '@review': resolve(__dirname, 'src/review'),
      '@shared': resolve(__dirname, 'src/shared'),
    },
  },
});
