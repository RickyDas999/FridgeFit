import { useState, type FormEvent } from 'react'
import {
  planMeals,
  type CanonicalUnit,
  type FallbackReason,
  type Macros,
  type MealLog,
  type MealPlan,
  type PlannedMeal,
} from './api'
import { formatQuantity } from './format'
import LogMeal from './LogMeal'

type OnMealLogged = (meal: MealLog, servings: number) => void

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

/** Where a planned meal is in the plan being followed: eaten, next to log, or still to come. */
type MealStep = 'eaten' | 'next' | 'later'

function PlannedMealItem(props: { meal: PlannedMeal; step: MealStep; onLogged: OnMealLogged }) {
  const { meal, step, onLogged } = props
  // Units for a shortfall the confirmation reports; every ingredient the plan touches is here.
  const units = new Map<number, CanonicalUnit>(
    [...meal.ingredients_used, ...meal.shortages].map((item) => [item.ingredient_id, item.unit]),
  )
  return (
    <li className={step === 'eaten' ? 'eaten' : undefined}>
      <p className="planned-meal-name">
        {meal.name}
        {step === 'eaten' && <span className="muted"> (eaten)</span>}
      </p>
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
      {/* The same confirmation as a recommendation: the backend consumes the stock it has now. */}
      {step === 'next' && (
        <LogMeal
          recipeId={meal.recipe_id}
          recipeName={meal.name}
          unitOf={(id) => units.get(id)}
          onLogged={onLogged}
        />
      )}
    </li>
  )
}

function PlanResult(props: {
  plan: MealPlan
  eaten: number
  onPlannedMealLogged: (index: number, meal: MealLog, servings: number) => void
}) {
  const { plan, eaten, onPlannedMealLogged } = props
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
          {plan.meals.map((meal, index) => (
            <PlannedMealItem
              key={meal.recipe_id}
              meal={meal}
              step={index < eaten ? 'eaten' : index === eaten ? 'next' : 'later'}
              onLogged={(logged, servings) => onPlannedMealLogged(index, logged, servings)}
            />
          ))}
        </ol>
      )}
      {eaten > 0 && eaten === plan.meals.length && (
        <p className="muted">You have eaten every meal in this plan.</p>
      )}
      {plan.remaining_at_end && plan.meals.length > 0 && (
        <p className="muted">Afterwards: {macroLine(plan.remaining_at_end)} left today.</p>
      )}
    </div>
  )
}

/**
 * "Plan my day": ask the API for the rest of today's meals and show the plan it returns.
 *
 * The plan is simulated meal by meal, so each meal's numbers already assume the ones before it
 * were eaten. Following it in order (the next meal, at the planned servings) keeps it valid, so
 * meals are logged one at a time and marked eaten. `mealsLogged` counts meals logged anywhere on
 * the dashboard; any other log (from the recommendations, or at different servings) is
 * something the plan did not simulate, so it is replaced by a note to plan again.
 */
function MealPlanner(props: { mealsLogged: number; onMealLogged: OnMealLogged }) {
  const { mealsLogged, onMealLogged } = props
  const [mealCount, setMealCount] = useState('2')
  const [maxPrep, setMaxPrep] = useState('')
  const [preference, setPreference] = useState('')
  const [planning, setPlanning] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // `mealsLogged` is the dashboard's count when the plan was requested; `eaten` counts plan
  // meals logged in order since. Any other log moves the dashboard's count past their sum.
  const [result, setResult] = useState<{
    plan: MealPlan
    mealsLogged: number
    eaten: number
  } | null>(null)
  const stale = result !== null && result.mealsLogged + result.eaten !== mealsLogged

  function handlePlannedMealLogged(index: number, meal: MealLog, servings: number) {
    if (result && index === result.eaten && servings === result.plan.meals[index].servings) {
      setResult({ ...result, eaten: result.eaten + 1 })
    }
    onMealLogged(meal, servings)
  }

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
    // Taken before the request: a meal logged while planning makes this plan stale too.
    const requestedAt = mealsLogged
    setPlanning(true)
    setError(null)
    try {
      const plan = await planMeals({
        meal_count: count,
        max_prep_minutes: prep,
        preference: preference.trim() || null,
      })
      setResult({ plan, mealsLogged: requestedAt, eaten: 0 })
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
      {result && !planning && stale && (
        <p className="muted plan-stale">
          A meal was logged that this plan did not include, so its stock and macros are out of
          date. Plan again for an updated one.
        </p>
      )}
      {result && !planning && !stale && (
        <PlanResult
          plan={result.plan}
          eaten={result.eaten}
          onPlannedMealLogged={handlePlannedMealLogged}
        />
      )}
    </section>
  )
}

export default MealPlanner
