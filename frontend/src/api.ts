// The one place the frontend learns where the FastAPI backend lives. Override it by setting
// VITE_API_BASE_URL (for example in frontend/.env.local); the default matches `uvicorn`'s.
export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8000'

export type HealthResult = { ok: true } | { ok: false; message: string }

/** Ask the backend's GET /health whether the API and its database are up. */
export async function checkHealth(): Promise<HealthResult> {
  let response: Response
  try {
    response = await fetch(`${API_BASE_URL}/health`)
  } catch {
    // fetch rejects only when no response arrives: server down, wrong URL, or CORS refusal.
    return { ok: false, message: `Cannot reach the backend at ${API_BASE_URL}.` }
  }

  if (!response.ok) {
    return { ok: false, message: `The backend responded with HTTP ${response.status}.` }
  }
  const body: { status?: string } = await response.json()
  return body.status === 'ok'
    ? { ok: true }
    : { ok: false, message: 'The backend responded, but did not report status "ok".' }
}
