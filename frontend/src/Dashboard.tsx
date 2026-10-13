import { useEffect, useState, type ReactNode } from 'react'
import {
  getInventory,
  getNutritionState,
  getRecommendations,
  getTodaysMeals,
  type CanonicalUnit,
  type InventoryItem,
  type Macros,
  type MealLog,
  type NutritionState,
  type Recommendation,
} from './api'

type Loadable<T> =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'ready'; data: T }

/** Load one API resource once, tracking loading and error state. `load` must be stable. */
function useResource<T>(load: () => Promise<T>): Loadable<T> {
  const [state, setState] = useState<Loadable<T>>({ status: 'loading' })

  useEffect(() => {
    // Ignore a response that arrives after the component unmounted.
    let active = true
    load().then(
      (data) => active && setState({ status: 'ready', data }),
      (error: Error) => active && setState({ status: 'error', message: error.message }),
    )
    return () => {
      active = false
    }
  }, [load])

  return state
}

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

const UNIT_LABELS: Record<CanonicalUnit, string> = { gram: 'g', milliliter: 'ml', count: '' }

/** Format a quantity with its unit, e.g. "450 g" or "6". */
function formatQuantity(quantity: number, unit: CanonicalUnit): string {
  const rounded = Math.round(quantity * 10) / 10
  return `${rounded}${UNIT_LABELS[unit] ? ` ${UNIT_LABELS[unit]}` : ''}`
}

/** Format a local, timezone-less ISO datetime from the API as a time of day, e.g. "08:00". */
function formatTime(isoDateTime: string): string {
  return new Date(isoDateTime).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
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

function RecommendationList({ items }: { items: Recommendation[] }) {
  if (items.length === 0) {
    return <p className="detail">No recipes can be made with what is on hand.</p>
  }
  return (
    <ol className="recommendation-list">
      {items.map((item) => {
        const missing = item.availability.ingredients.filter((i) => i.is_missing)
        const expired = item.expiry_urgency.expired_batches.length
        const recent = item.recent_frequency.times_eaten_recently
        return (
          <li key={item.recipe_id}>
            <div className="recommendation-head">
              <span className="recommendation-name">{item.name}</span>
              <span className="score" title="Combined score from the API">
                {Math.round(item.score * 100)}
              </span>
            </div>
            <div className="tags">
              <span className="tag">
                {Math.round(item.availability.score * 100)}% available
              </span>
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

function MealList({ meals }: { meals: MealLog[] }) {
  if (meals.length === 0) {
    return <p className="detail">No meals logged today.</p>
  }
  return (
    <ul className="plain-list">
      {meals.map((meal) => (
        <li key={meal.id}>
          <span>
            <span className="detail">{formatTime(meal.consumed_at)}</span> {meal.name}
          </span>
          <span className="detail">
            {Math.round(meal.calories)} kcal ·{' '}
            {meal.rating === null ? 'Not rated' : `Rated ${meal.rating}/5`}
          </span>
        </li>
      ))}
    </ul>
  )
}

function Dashboard() {
  const nutrition = useResource(getNutritionState)
  const recommendations = useResource(getRecommendations)
  const inventory = useResource(getInventory)
  const meals = useResource(getTodaysMeals)

  return (
    <div className="dashboard">
      <Panel title="What to make" state={recommendations} className="span-rows">
        {(items) => <RecommendationList items={items} />}
      </Panel>
      <Panel title="Today's nutrition" state={nutrition}>
        {(state) => <NutritionSummary state={state} />}
      </Panel>
      <Panel title="Eaten today" state={meals}>
        {(items) => <MealList meals={items} />}
      </Panel>
      <Panel title="In the kitchen" state={inventory}>
        {(items) => <InventoryList items={items} />}
      </Panel>
    </div>
  )
}

export default Dashboard
