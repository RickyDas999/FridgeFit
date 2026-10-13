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

  return (
    <main className="shell">
      <header className="app-header">
        <div>
          <h1>FridgeFit</h1>
          <p className="tagline">What should I make with what I have?</p>
        </div>
        <div className="health" aria-live="polite">
          {health === null && <span className="status checking">Checking backend…</span>}
          {health?.ok && <span className="status connected">Backend connected</span>}
          {health && !health.ok && (
            <>
              <span className="status unavailable" title={health.message}>
                Backend unavailable
              </span>
              <button type="button" onClick={refreshHealth}>
                Check again
              </button>
            </>
          )}
        </div>
      </header>

      {health && !health.ok && (
        <p className="error-text">
          {health.message} Start it with <code>.venv/bin/uvicorn app.api.main:app</code> (API:{' '}
          <code>{API_BASE_URL}</code>).
        </p>
      )}

      <Dashboard />
    </main>
  )
}

export default App
