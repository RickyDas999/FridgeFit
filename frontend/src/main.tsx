import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
// Self-hosted, so the demo does not depend on a network connection for fonts.
import '@fontsource-variable/atkinson-hyperlegible-next'
import './index.css'
import App from './App.tsx'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
