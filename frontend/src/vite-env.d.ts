/// <reference types="vite/client" />

// Typed Vite environment variables. Only variables prefixed with VITE_ reach the browser.
interface ImportMetaEnv {
  /** Base URL of the FastAPI backend, e.g. http://127.0.0.1:8000. */
  readonly VITE_API_BASE_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
