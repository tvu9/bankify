import { defineConfig } from 'vite';

// Dev-only: forward API calls to server.py (python3 server.py on :3000)
// so `npm run dev` gets hot reload while /api/* still works.
export default defineConfig({
  server: {
    port: 5173,
    proxy: {
      '/api': { target: 'http://127.0.0.1:3000', changeOrigin: true },
    },
  },
});
