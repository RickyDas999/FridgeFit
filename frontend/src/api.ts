// The one place the frontend learns where the FastAPI backend lives. Override it by setting
// VITE_API_BASE_URL (for example in frontend/.env.local); the default matches `uvicorn`'s.
export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8000'

// Response shapes, mirroring the backend's Pydantic schemas (app/api/*.py). Dates and datetimes
// arrive as ISO strings; datetimes are local time without a timezone.

export type CanonicalUnit = 'gram' | 'milliliter' | 'count'
export type IngredientRole = 'primary' | 'supporting' | 'optional'

export type Macros = { calories: number; protein: number; carbs: number; fat: number }

export type NutritionState = {
  as_of: string
  goal: (Macros & { id: number; effective_date: string }) | null
  remaining: Macros | null
}

export type InventoryItem = {
  ingredient_id: number
  name: string
  canonical_unit: CanonicalUnit
  quantity_on_hand: number
}

export type Recommendation = {
  recipe_id: number
  name: string
  score: number
  availability: {
    score: number
    ingredients: {
      ingredient_id: number
      name: string
      role: IngredientRole
      quantity_per_serving: number
      quantity_on_hand: number
      fraction_available: number
      is_missing: boolean
    }[]
  }
  expiry_urgency: {
    score: number
    expired_batches: { batch_id: number; ingredient_id: number; use_by_date: string }[]
  }
  macro_fit: { score: number; per_serving: Macros } | null
  enjoyment: { score: number; average_rating: number | null; rating_count: number }
  recent_frequency: { times_eaten_recently: number; last_eaten_on: string | null }
}

export type MealLog = Macros & {
  id: number
  recipe_id: number | null
  name: string
  consumed_at: string
  idempotency_key: string | null
  ingredients: { ingredient_id: number; name: string; quantity: number }[]
  rating: number | null
}

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

/** GET a JSON resource, turning network failures and non-2xx responses into Errors. */
async function getJson<T>(path: string): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${API_BASE_URL}${path}`)
  } catch {
    throw new Error(`Cannot reach the backend at ${API_BASE_URL}.`)
  }
  if (!response.ok) {
    throw new Error(`GET ${path} failed with HTTP ${response.status}.`)
  }
  return (await response.json()) as T
}

// No date parameter: each endpoint defaults to today on the server's clock.
export const getNutritionState = () => getJson<NutritionState>('/nutrition-state')
export const getInventory = () => getJson<InventoryItem[]>('/inventory')
export const getRecommendations = () => getJson<Recommendation[]>('/recommendations')
export const getTodaysMeals = () => getJson<MealLog[]>('/meal-logs')
