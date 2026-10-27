import { useState, type FormEvent } from 'react'
import { planMeals, type FallbackReason, type Macros, type MealPlan, type PlannedMeal } from './api'
import { formatQuantity } from './format'

// Why the AI plan was not used, in plain words. ai_disabled needs no warning: the rules are
// simply how planning works when AI is off.
const FALLBACK_SENTENCES: Record<FallbackReason, string | null> = {
  ai_disabled: null,
  ai_limit: 'AI planning has reached its limit for today.',
  ai_failed: 'Claude could not finish a plan this time.',
  ai_plan_invalid: "Claude's plan did not pass FridgeFit's checks.",
}

/** Read an optional whole number from a text field; undefined when it is not one in range. */
function parseWhole(text: string, min: number, max: number): number | null | undefined {
  if (text.trim() === '') return null
  const value = Number(text)
  return Number.isInteger(value) && value >= min && value <= max ? value : undefined
}

function macroLine(macros: Macros): string {
  return `${Math.round(macros.calories).toLocaleString()} kcal, ${Math.round(macros.protein)} g protein`
}

function PlannedMealItem({ meal }: { meal: PlannedMeal }) {
  return (
    <li>
      <p className="planned-meal-name">{meal.name}</p>
      <p className="muted">
        {meal.prep_minutes} min prep, {macroLine(meal.macros)}
      </p>
      <p>
        Uses{' '}
        {meal.ingredients_used
          .map((item) => `${item.name.toLowerCase()} ${formatQuantity(item.quantity, item.unit)}`)
          .join(', ')}
      </p>
      {meal.shortages.length > 0 && (
        <p>
          <span className="flag">
            Short of{' '}
          {meal.shortages
            .map(
              (item) =>
                `${item.name.toLowerCase()} (need ${formatQuantity(item.needed, item.unit)}, ` +
                `have ${formatQuantity(item.available, item.unit)})`,
            )
            .join(', ')}
          </span>
        </p>
      )}
    </li>
  )
}

function PlanResult({ plan }: { plan: MealPlan }) {
  const reason = plan.fallback_reason && FALLBACK_SENTENCES[plan.fallback_reason]
  return (
    <div className="plan-result">
      <p className="plan-source">
        {plan.source === 'ai' ? 'Planned by Claude' : "Planned by FridgeFit's rules"}
      </p>
      {plan.explanation && <p className="plan-explanation">{plan.explanation}</p>}
      {reason && <p className="muted">{reason} This plan uses FridgeFit's rules instead.</p>}

      {plan.meals.length === 0 ? (
        <p className="muted">Nothing can be planned with what is on hand.</p>
      ) : (
        <ol className="planned-meals">
          {plan.meals.map((meal) => (
            <PlannedMealItem key={meal.recipe_id} meal={meal} />
          ))}
        </ol>
      )}
      {plan.remaining_at_end && plan.meals.length > 0 && (
        <p className="muted">Afterwards: {macroLine(plan.remaining_at_end)} left today.</p>
      )}
    </div>
  )
}

/** "Plan my day": ask the API for the rest of today's meals and show the plan it returns. */
function MealPlanner() {
  const [mealCount, setMealCount] = useState('2')
  const [maxPrep, setMaxPrep] = useState('')
  const [preference, setPreference] = useState('')
  const [planning, setPlanning] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [plan, setPlan] = useState<MealPlan | null>(null)

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    const count = parseWhole(mealCount, 1, 5)
    const prep = parseWhole(maxPrep, 1, 240)
    if (count == null) {
      setError('Choose between 1 and 5 meals.')
      return
    }
    if (prep === undefined) {
      setError('Max prep time must be a whole number of minutes from 1 to 240, or empty.')
      return
    }
    setPlanning(true)
    setError(null)
    try {
      setPlan(
        await planMeals({
          meal_count: count,
          max_prep_minutes: prep,
          preference: preference.trim() || null,
        }),
      )
    } catch (failure) {
      setError((failure as Error).message)
    } finally {
      setPlanning(false)
    }
  }

  return (
    <section className="shelf planner">
      <h2>Plan my day</h2>
      <form className="plan-form" onSubmit={handleSubmit} noValidate>
        <label>
          Meals
          <input
            type="number"
            inputMode="numeric"
            min="1"
            max="5"
            value={mealCount}
            disabled={planning}
            onChange={(event) => setMealCount(event.target.value)}
          />
        </label>
        <label>
          Max prep (min)
          <input
            type="number"
            inputMode="numeric"
            min="1"
            max="240"
            placeholder="Any"
            value={maxPrep}
            disabled={planning}
            onChange={(event) => setMaxPrep(event.target.value)}
          />
        </label>
        <label className="plan-preference">
          Preference
          <input
            type="text"
            maxLength={300}
            placeholder="e.g. something light"
            value={preference}
            disabled={planning}
            onChange={(event) => setPreference(event.target.value)}
          />
        </label>
        <button type="submit" disabled={planning}>
          {planning ? 'Planning…' : 'Plan'}
        </button>
      </form>
      {planning && <p className="muted">This can take up to a minute.</p>}
      {error && <p className="error-text">{error}</p>}
      {plan && !planning && <PlanResult plan={plan} />}
    </section>
  )
}

export default MealPlanner
