import { useEffect, useState } from 'react'
import { API_BASE_URL, checkHealth, type HealthResult } from './api'
import Dashboard from './Dashboard'

function App() {
  // null while a check is in flight.
  const [health, setHealth] = useState<HealthResult | null>(null)

  async function refreshHealth() {
    setHealth(null)
    setHealth(await checkHealth())
  }

  useEffect(() => {
    void refreshHealth()
  }, [])

  const status = health === null ? 'checking' : health.ok ? 'connected' : 'unavailable'
  const statusText = { checking: 'Connecting…', connected: 'Connected', unavailable: 'Offline' }

  return (
    <main className="shell">
      <header className="app-header">
        <h1>FridgeFit</h1>
        <p className="tagline">What should I make with what I have?</p>
        <p className={`health ${status}`} aria-live="polite">
          <span className="health-dot" aria-hidden="true" />
          {statusText[status]}
          {status === 'unavailable' && (
            <button type="button" className="link-button" onClick={refreshHealth}>
              Try again
            </button>
          )}
        </p>
      </header>

      {health && !health.ok && (
        <p className="banner error" role="alert">
          {health.message} Start the API from the repository root with{' '}
          <code>.venv/bin/uvicorn app.api.main:app --reload</code>, then try again. The app
          expects it at <code>{API_BASE_URL}</code>.
        </p>
      )}

      <Dashboard />
    </main>
  )
}

export default App
