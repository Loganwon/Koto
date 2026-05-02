// ═══════════════════════════════════════════════════════════════
// Koto 文件助手 — Vite 构建配置
// ═══════════════════════════════════════════════════════════════
import { defineConfig } from 'vite';

export default defineConfig({
  base: './',

  server: {
    port: 5173,
    open: true,
    // 将 Socket.IO 请求代理到 Flask 后端
    proxy: {
      '/socket.io': {
        target: 'http://127.0.0.1:5000',
        ws: true,
        changeOrigin: true,
      },
    },
  },

  build: {
    outDir: '../static/univer-dist',
    emptyOutDir: false,   // ← false: 保留 esbuild 单独构建的 sheets-main.js/css
  },
});
