import { useState, type ReactNode } from 'react'
import {
  getInventory,
  getNutritionState,
  getRecommendations,
  getTodaysMeals,
  type InventoryItem,
  type Macros,
  type MealLog,
  type NutritionState,
  type Recommendation,
} from './api'
import { formatQuantity, formatScore, formatTime } from './format'
import RateMeal from './RateMeal'
import RecommendationDetail from './RecommendationDetail'
import { useResource, type Loadable } from './useResource'

/** A titled panel that shows loading and error states, or its content once data is ready. */
function Panel<T>(props: {
  title: string
  state: Loadable<T>
  className?: string
  children: (data: T) => ReactNode
}) {
  const { title, state, className = '', children } = props
  return (
    <section className={`card ${className}`}>
      <h2>{title}</h2>
      {state.status === 'loading' && <p className="detail">Loading…</p>}
      {state.status === 'error' && <p className="error-text">{state.message}</p>}
      {state.status === 'ready' && children(state.data)}
    </section>
  )
}

const MACRO_ROWS: { key: keyof Macros; label: string; unit: string }[] = [
  { key: 'calories', label: 'Calories', unit: 'kcal' },
  { key: 'protein', label: 'Protein', unit: 'g' },
  { key: 'carbs', label: 'Carbs', unit: 'g' },
  { key: 'fat', label: 'Fat', unit: 'g' },
]

function NutritionSummary({ state }: { state: NutritionState }) {
  if (!state.goal || !state.remaining) {
    return <p className="detail">No nutrition goal is in effect yet.</p>
  }
  const { goal, remaining } = state
  return (
    <ul className="macro-list">
      {MACRO_ROWS.map(({ key, label, unit }) => {
        const left = remaining[key]
        // Bar width shows the remaining share of the goal; it is display scaling only.
        const width = goal[key] > 0 ? Math.min(Math.max(left / goal[key], 0), 1) * 100 : 0
        return (
          <li key={key}>
            <div className="macro-row">
              <span>{label}</span>
              <span className={left < 0 ? 'error-text' : ''}>
                {left < 0
                  ? `${Math.round(-left)} ${unit} over`
                  : `${Math.round(left)} of ${Math.round(goal[key])} ${unit} left`}
              </span>
            </div>
            <div className="bar">
              <div className="bar-fill" style={{ width: `${width}%` }} />
            </div>
          </li>
        )
      })}
    </ul>
  )
}

function RecommendationList(props: {
  items: Recommendation[]
  onMealLogged: (meal: MealLog, servings: number) => void
}) {
  const { items, onMealLogged } = props
  // The recipe whose detail is open; one at a time.
  const [openRecipeId, setOpenRecipeId] = useState<number | null>(null)

  if (items.length === 0) {
    return <p className="detail">No recipes can be made with what is on hand.</p>
  }
  return (
    <ol className="recommendation-list">
      {items.map((item) => {
        const missing = item.availability.ingredients.filter((i) => i.is_missing)
        const expired = item.expiry_urgency.expired_batches.length
        const recent = item.recent_frequency.times_eaten_recently
        const isOpen = openRecipeId === item.recipe_id
        return (
          <li key={item.recipe_id}>
            <button
              type="button"
              className="recommendation-summary"
              aria-expanded={isOpen}
              onClick={() => setOpenRecipeId(isOpen ? null : item.recipe_id)}
            >
              <div className="recommendation-head">
                <span className="recommendation-name">{item.name}</span>
                <span className="score" title="Combined score from the API">
                  {formatScore(item.score)}
                </span>
              </div>
              <div className="tags">
                <span className="tag">{formatScore(item.availability.score)}% available</span>
                {missing.length > 0 && (
                  <span className="tag warn">Missing {missing.map((i) => i.name).join(', ')}</span>
                )}
                {expired > 0 && (
                  <span className="tag warn">
                    {expired} expired batch{expired > 1 ? 'es' : ''}
                  </span>
                )}
                {recent > 0 && <span className="tag">Eaten {recent}× this week</span>}
              </div>
            </button>
            {isOpen && <RecommendationDetail recommendation={item} onMealLogged={onMealLogged} />}
          </li>
        )
      })}
    </ol>
  )
}

function InventoryList({ items }: { items: InventoryItem[] }) {
  if (items.length === 0) {
    return <p className="detail">Nothing in stock.</p>
  }
  return (
    <ul className="plain-list">
      {items.map((item) => (
        <li key={item.ingredient_id}>
          <span>{item.name}</span>
          <span className="detail">{formatQuantity(item.quantity_on_hand, item.canonical_unit)}</span>
        </li>
      ))}
    </ul>
  )
}

function MealList(props: {
  meals: MealLog[]
  onRated: (meal: MealLog, rating: number | null) => void
}) {
  const { meals, onRated } = props
  if (meals.length === 0) {
    return <p className="detail">No meals logged today.</p>
  }
  return (
    <ul className="plain-list meal-list">
      {meals.map((meal) => (
        <li key={meal.id}>
          <span>
            <span className="detail">{formatTime(meal.consumed_at)}</span> {meal.name}
            <span className="detail"> · {Math.round(meal.calories)} kcal</span>
          </span>
          {meal.rating === null ? (
            <RateMeal meal={meal} onRated={onRated} />
          ) : (
            <span className="detail">Rated {meal.rating}/5</span>
          )}
        </li>
      ))}
    </ul>
  )
}

function Dashboard() {
  // Bumped after a write so every panel refetches.
  const [version, setVersion] = useState(0)
  const [notice, setNotice] = useState<string | null>(null)

  const nutrition = useResource(getNutritionState, version)
  const recommendations = useResource(getRecommendations, version)
  const inventory = useResource(getInventory, version)
  const meals = useResource(getTodaysMeals, version)

  function handleMealLogged(meal: MealLog, servings: number) {
    setNotice(`Logged ${meal.name} (${servings} serving${servings === 1 ? '' : 's'}).`)
    setVersion((current) => current + 1)
  }

  // A rating changes the meal's row and its recipe's enjoyment score, so refetch everything.
  function handleRated(meal: MealLog, rating: number | null) {
    setNotice(
      rating === null ? `${meal.name} was already rated.` : `Rated ${meal.name} ${rating}/5.`,
    )
    setVersion((current) => current + 1)
  }

  return (
    <>
      {notice && (
        <p className="notice" role="status">
          {notice}{' '}
          <button type="button" className="link-button" onClick={() => setNotice(null)}>
            Dismiss
          </button>
        </p>
      )}
      <div className="dashboard">
        <Panel title="What to make" state={recommendations} className="span-rows">
          {(items) => <RecommendationList items={items} onMealLogged={handleMealLogged} />}
        </Panel>
        <Panel title="Today's nutrition" state={nutrition}>
          {(state) => <NutritionSummary state={state} />}
        </Panel>
        <Panel title="Eaten today" state={meals}>
          {(items) => <MealList meals={items} onRated={handleRated} />}
        </Panel>
        <Panel title="In the kitchen" state={inventory}>
          {(items) => <InventoryList items={items} />}
        </Panel>
      </div>
    </>
  )
}

export default Dashboard
