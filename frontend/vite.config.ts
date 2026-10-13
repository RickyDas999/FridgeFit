import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // The backend's CORS allows only this port (LOCAL_FRONTEND_ORIGINS in app/api/main.py).
    // strictPort fails loudly if it is taken, instead of moving to a port CORS would block.
    port: 5173,
    strictPort: true,
  },
})
