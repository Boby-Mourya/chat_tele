import { fileURLToPath, URL } from 'node:url';
import react from '@vitejs/plugin-react';
import { defineConfig, loadEnv } from 'vite';

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, fileURLToPath(new URL('.', import.meta.url)));
  return {
    plugins: [react()],
    resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
    server: {
      port: 5173,
      allowedHosts: ['isolation-unaligned-catalog.ngrok-free.dev'],
      proxy: {
        '/api': { target: process.env.VITE_DEV_API_URL ?? env.VITE_DEV_API_URL ?? 'http://localhost:8000', changeOrigin: true },
        '/storage': { target: process.env.VITE_DEV_STORAGE_URL ?? env.VITE_DEV_STORAGE_URL ?? 'http://localhost:9010', changeOrigin: true, rewrite: (path) => path.replace(/^\/storage/, '') },
      },
    },
  };
});
