import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// In docker compose, the built assets are served by nginx which also proxies
// /api to the backend. In `npm run dev` we proxy /api to http://backend:8000
// (or localhost:8000 if running outside compose).
export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 5173,
    proxy: {
      '/api': {
        target: process.env.VITE_API_TARGET || 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
  },
})
