import { useEffect, useState } from 'react'
import { API_BASE_URL, checkHealth, type HealthResult } from './api'

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
      <header>
        <h1>FridgeFit</h1>
        <p className="tagline">What should I make with what I have?</p>
      </header>

      <section className="card" aria-live="polite">
        <h2>Backend</h2>
        {health === null && <p className="status checking">Checking connection…</p>}
        {health?.ok && <p className="status connected">Connected</p>}
        {health && !health.ok && (
          <>
            <p className="status unavailable">Unavailable</p>
            <p className="detail">{health.message}</p>
          </>
        )}
        <p className="detail">
          API: <code>{API_BASE_URL}</code>
        </p>
        <button type="button" onClick={refreshHealth} disabled={health === null}>
          Check again
        </button>
      </section>
    </main>
  )
}

export default App
