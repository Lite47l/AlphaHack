import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Dev: /api проксируется на Go-шлюз (backend :8080). В Docker то же делает nginx.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: process.env.VITE_API_PROXY ?? 'http://localhost:8080',
        changeOrigin: true,
      },
    },
  },
  preview: { port: 4173 },
  build: { outDir: 'dist', sourcemap: false },
});
