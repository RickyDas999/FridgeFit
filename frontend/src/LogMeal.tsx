import { useState, type FormEvent } from 'react'
import { confirmMeal, type CanonicalUnit, type MealLog, type Shortfall } from './api'
import { formatQuantity } from './format'

type Props = {
  recipeId: number
  recipeName: string
  /** Units for shortfall quantities, when the recipe has loaded. */
  unitOf: (ingredientId: number) => CanonicalUnit | undefined
  onLogged: (meal: MealLog, servings: number) => void
}

/**
 * "I ate this": confirm servings of a recipe as a meal through the API.
 *
 * Each kind of submission keeps its Idempotency-Key until it succeeds, so retrying after a
 * network failure reuses the key and the backend cannot log the meal twice. Changing servings
 * starts a new operation with new keys. Logging anyway after a shortfall is a different request,
 * so it has its own key.
 */
function LogMeal({ recipeId, recipeName, unitOf, onLogged }: Props) {
  const [open, setOpen] = useState(false)
  const [servings, setServings] = useState('1')
  const [keys, setKeys] = useState<{ normal: string | null; override: string | null }>({
    normal: null,
    override: null,
  })
  const [submitting, setSubmitting] = useState(false)
  const [shortfalls, setShortfalls] = useState<Shortfall[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  function reset() {
    setOpen(false)
    setServings('1')
    setKeys({ normal: null, override: null })
    setShortfalls(null)
    setError(null)
  }

  async function submit(allowShortfall: boolean) {
    const amount = Number(servings)
    if (!Number.isFinite(amount) || amount <= 0) {
      setError('Enter a number of servings above 0.')
      return
    }
    const kind = allowShortfall ? 'override' : 'normal'
    const idempotencyKey = keys[kind] ?? crypto.randomUUID()
    setKeys((current) => ({ ...current, [kind]: idempotencyKey }))
    setSubmitting(true)
    setError(null)
    try {
      const result = await confirmMeal(recipeId, amount, { allowShortfall, idempotencyKey })
      if (result.status === 'shortfall') {
        setShortfalls(result.shortfalls)
      } else {
        reset()
        onLogged(result.meal, amount)
      }
    } catch (failure) {
      // Keys are kept, so submitting again retries the same operation.
      setError((failure as Error).message)
    } finally {
      setSubmitting(false)
    }
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    void submit(false)
  }

  if (!open) {
    return (
      <button type="button" onClick={() => setOpen(true)}>
        I ate this
      </button>
    )
  }

  return (
    // noValidate: the step only sets the arrow increments; any positive amount is allowed.
    <form className="log-meal" onSubmit={handleSubmit} noValidate>
      <label>
        Servings of {recipeName}
        <input
          type="number"
          inputMode="decimal"
          min="0"
          step="0.5"
          value={servings}
          disabled={submitting}
          onChange={(event) => {
            setServings(event.target.value)
            setKeys({ normal: null, override: null })
            setShortfalls(null)
            setError(null)
          }}
        />
      </label>
      <div className="form-actions">
        <button type="submit" disabled={submitting}>
          {submitting ? 'Logging…' : 'Log meal'}
        </button>
        <button type="button" className="secondary" onClick={reset} disabled={submitting}>
          Cancel
        </button>
      </div>

      {error && <p className="error-text">{error}</p>}

      {shortfalls && (
        <div className="shortfall">
          <p>Not enough in the fridge for {servings} serving{Number(servings) === 1 ? '' : 's'}.</p>
          <ul>
            {shortfalls.map((item) => {
              const unit = unitOf(item.ingredient_id)
              return (
                <li key={item.ingredient_id}>
                  {item.name}: need {formatQuantity(item.quantity_needed, unit)}, have{' '}
                  {formatQuantity(item.quantity_available, unit)}
                </li>
              )
            })}
          </ul>
          <button type="button" onClick={() => void submit(true)} disabled={submitting}>
            Log anyway with what I have
          </button>
        </div>
      )}
    </form>
  )
}

export default LogMeal
