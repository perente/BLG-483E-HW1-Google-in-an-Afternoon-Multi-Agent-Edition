import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// During development, API calls are proxied to the backend server.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/index':              'http://localhost:8000',
      '/search':             'http://localhost:8000',
      '/jobs':               'http://localhost:8000',
      '/pause':              'http://localhost:8000',
      '/resume':             'http://localhost:8000',
    },
  },
})
