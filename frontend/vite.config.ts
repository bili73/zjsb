import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// Dev server proxies to the loopback backend; production serves same-origin
// from backend static files (see backend/ocr_app/api.py), so no CORS is needed.
export default defineConfig({
  plugins: [vue()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8765', changeOrigin: false },
      '/health': { target: 'http://127.0.0.1:8765', changeOrigin: false },
    },
  },
  build: { outDir: 'dist', sourcemap: false },
})
