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
    // Earliest unexpired use-by date per recipe ingredient (null when undated or only expired).
    ingredients: { ingredient_id: number; use_by_date: string | null; expiring_soon: boolean }[]
  }
  macro_fit: { score: number; per_serving: Macros } | null
  enjoyment: { score: number; average_rating: number | null; rating_count: number }
  recent_frequency: { times_eaten_recently: number; last_eaten_on: string | null }
}

export type Recipe = {
  id: number
  name: string
  instructions: string[]
  source_url: string | null
  prep_minutes: number
  servings: number
  ingredients: {
    ingredient_id: number
    name: string
    canonical_unit: CanonicalUnit
    quantity: number
    role: IngredientRole
  }[]
  macros: Macros
  macros_per_serving: Macros
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

export type Shortfall = {
  ingredient_id: number
  name: string
  quantity_needed: number
  quantity_available: number
}

export type ConfirmResult =
  | { status: 'logged'; meal: MealLog; replayed: boolean }
  | { status: 'shortfall'; shortfalls: Shortfall[] }

export type PlanRequest = {
  meal_count: number
  max_prep_minutes: number | null
  preference: string | null
}

export type FallbackReason = 'ai_disabled' | 'ai_failed' | 'ai_plan_invalid' | 'ai_limit'

export type PlannedMeal = {
  recipe_id: number
  name: string
  prep_minutes: number
  servings: number
  ingredients_used: { ingredient_id: number; name: string; unit: CanonicalUnit; quantity: number }[]
  shortages: {
    ingredient_id: number
    name: string
    unit: CanonicalUnit
    needed: number
    available: number
  }[]
  macros: Macros
  remaining_after: Macros | null
}

export type MealPlan = {
  source: 'ai' | 'baseline'
  // Written by Claude; only present for an AI plan. Every number elsewhere is FridgeFit's.
  explanation: string | null
  fallback_reason: FallbackReason | null
  meals: PlannedMeal[]
  remaining_at_end: Macros | null
}

export type HealthResult = { ok: true } | { ok: false; message: string }

/** Thrown when no response arrives at all (server down, wrong URL, or CORS refusal). */
export class BackendUnreachable extends Error {
  constructor() {
    super(`Cannot reach the backend at ${API_BASE_URL}.`)
  }
}

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
    throw new BackendUnreachable()
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
export const getRecipe = (recipeId: number) => getJson<Recipe>(`/recipes/${recipeId}`)

/** Turn a FastAPI error response into a readable message (a `detail` string or error list). */
async function describeError(response: Response): Promise<string> {
  try {
    const body: { detail?: unknown } = await response.json()
    if (typeof body.detail === 'string') return body.detail
    if (Array.isArray(body.detail)) {
      return body.detail.map((error: { msg?: string }) => error.msg ?? 'Invalid input').join('; ')
    }
  } catch {
    // Not JSON; fall through to the status code.
  }
  return `The backend responded with HTTP ${response.status}.`
}

/**
 * Log a meal made from a recipe, consuming its ingredients (POST /recipes/{id}/confirm).
 *
 * The caller supplies the Idempotency-Key so it can reuse it when retrying the same submission:
 * the backend then returns the original meal (HTTP 200) instead of logging it twice. A 409 is
 * returned as a shortfall result rather than an error, so the caller can offer to log anyway.
 */
export async function confirmMeal(
  recipeId: number,
  servings: number,
  options: { allowShortfall: boolean; idempotencyKey: string },
): Promise<ConfirmResult> {
  let response: Response
  try {
    response = await fetch(`${API_BASE_URL}/recipes/${recipeId}/confirm`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Idempotency-Key': options.idempotencyKey },
      body: JSON.stringify({ servings, allow_shortfall: options.allowShortfall }),
    })
  } catch {
    throw new BackendUnreachable()
  }

  if (response.status === 409) {
    const body: { detail: { shortfalls: Shortfall[] } } = await response.json()
    return { status: 'shortfall', shortfalls: body.detail.shortfalls }
  }
  if (!response.ok) {
    throw new Error(await describeError(response))
  }
  return { status: 'logged', meal: await response.json(), replayed: response.status === 200 }
}

/**
 * Plan the rest of today's meals (POST /meal-plans). Nothing is written. The backend always
 * answers 200 with a plan: Claude's when it passes FridgeFit's checks, otherwise its own.
 */
export async function planMeals(request: PlanRequest): Promise<MealPlan> {
  let response: Response
  try {
    response = await fetch(`${API_BASE_URL}/meal-plans`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    })
  } catch {
    throw new BackendUnreachable()
  }
  if (!response.ok) {
    throw new Error(await describeError(response))
  }
  return (await response.json()) as MealPlan
}

/**
 * Rate a logged meal from 1 to 5 (POST /meal-logs/{id}/feedback). Each meal can be rated once:
 * a second rating gets 409, returned as `already_rated` so the caller can show the stored one.
 */
export async function rateMeal(
  mealLogId: number,
  rating: number,
): Promise<'rated' | 'already_rated'> {
  let response: Response
  try {
    response = await fetch(`${API_BASE_URL}/meal-logs/${mealLogId}/feedback`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ rating }),
    })
  } catch {
    throw new BackendUnreachable()
  }
  if (response.status === 409) return 'already_rated'
  if (!response.ok) {
    throw new Error(await describeError(response))
  }
  return 'rated'
}
