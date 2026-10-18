import { defineConfig } from 'vite';
import { resolve } from 'path';

export default defineConfig({
  server: {
    port: 3000,
    open: true,
    host: true,
    allowedHosts: true,
    proxy: {
      '/api/agent': {
        target: `http://127.0.0.1:${process.env.VITE_AGENT_PORT || process.env.VITE_BACKEND_PORT || 8000}`,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api\/agent/, '/api/v1'),
      },
      '/api/merchant': {
        target: `http://127.0.0.1:${process.env.VITE_MERCHANT_PORT || process.env.VITE_BACKEND_PORT || 8000}`,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api\/merchant/, '/api/v1'),
      },
      '/api/payment': {
        target: `http://127.0.0.1:${process.env.VITE_PAYMENT_PORT || process.env.VITE_BACKEND_PORT || 8000}`,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api\/payment/, '/api/v1'),
      },
      '/api/v1': {
        target: `http://127.0.0.1:${process.env.VITE_BACKEND_PORT || 8000}`,
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    assetsDir: 'assets',
    rollupOptions: {
      input: {
        main: resolve(__dirname, 'index.html'),
        login: resolve(__dirname, 'login.html'),
      },
    },
  },
});

