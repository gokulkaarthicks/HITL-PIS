import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// The client talks to the API at VITE_API_BASE_URL (default http://localhost:8000).
//
// The `/api` proxy below is an optional dev convenience: set
// VITE_API_BASE_URL=/api and requests go same-origin through Vite, which avoids
// CORS entirely while developing. It has no effect on a production build --
// Cloudflare Pages serves static files only, so deployments must use the
// absolute backend URL.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': {
        // 127.0.0.1 rather than localhost: on machines where localhost resolves
        // to ::1 first, "localhost" can silently reach a different process
        // listening on IPv6 than the uvicorn server bound to IPv4.
        target: process.env.VITE_PROXY_TARGET || 'http://127.0.0.1:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
})
