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
import AddGroceries from './AddGroceries'
import MealPlanner from './MealPlanner'
import RateMeal from './RateMeal'
import RecommendationDetail from './RecommendationDetail'
import { useResource, type Loadable } from './useResource'

/** A titled section that shows loading and error states, or its content once data is ready. */
function Section<T>(props: {
  title: string
  state: Loadable<T>
  className: string
  children: (data: T) => ReactNode
}) {
  const { title, state, className, children } = props
  return (
    <section className={className}>
      <h2>{title}</h2>
      {state.status === 'loading' && <p className="muted">Loading…</p>}
      {/* When the API is down, the header banner explains it once; sections just wait. */}
      {state.status === 'error' &&
        (state.offline ? (
          <p className="muted">Waiting for the API…</p>
        ) : (
          <p className="error-text">{state.message}</p>
        ))}
      {state.status === 'ready' && children(state.data)}
    </section>
  )
}

/**
 * How full a meter reads. Display thresholds only: the remaining amounts come from the API.
 * Below 15% of the goal left reads as "low", and a negative remainder as "over".
 */
function meterState(left: number, goal: number): 'ok' | 'low' | 'over' {
  if (left < 0) return 'over'
  return goal > 0 && left / goal < 0.15 ? 'low' : 'ok'
}

function Meter({ left, goal, label }: { left: number; goal: number; label: string }) {
  // The fill is the remaining share of today's goal; it is display scaling only.
  const share = goal > 0 ? Math.min(Math.max(left / goal, 0), 1) : 0
  return (
    <div
      className={`meter ${meterState(left, goal)}`}
      role="img"
      aria-label={`${label}: ${Math.round(share * 100)}% of today's goal left`}
    >
      <div className="meter-fill" style={{ width: `${share * 100}%` }} />
    </div>
  )
}

const MACROS: { key: Exclude<keyof Macros, 'calories'>; label: string }[] = [
  { key: 'protein', label: 'Protein' },
  { key: 'carbs', label: 'Carbs' },
  { key: 'fat', label: 'Fat' },
]

function NutritionSummary({ state }: { state: NutritionState }) {
  if (!state.goal || !state.remaining) {
    return <p className="muted">No nutrition goal is set, so macro fit is left out of ranking.</p>
  }
  const { goal, remaining } = state
  const caloriesLeft = Math.round(remaining.calories)
  return (
    <>
      <p className="calories">
        {caloriesLeft < 0 ? (
          <span className="calories-figure over">{Math.abs(caloriesLeft).toLocaleString()}</span>
        ) : (
          <span className="calories-figure">{caloriesLeft.toLocaleString()}</span>
        )}
        <span className="calories-label">
          {caloriesLeft < 0 ? 'kcal over' : 'kcal left'} of {Math.round(goal.calories).toLocaleString()}
        </span>
      </p>
      <Meter left={remaining.calories} goal={goal.calories} label="Calories" />

      <ul className="macro-list">
        {MACROS.map(({ key, label }) => {
          const left = Math.round(remaining[key])
          return (
            <li key={key}>
              <span className="macro-name">{label}</span>
              <span className={`macro-value ${left < 0 ? 'error-text' : ''}`}>
                {left < 0 ? `${-left} g over` : `${left} g left`}
              </span>
              <Meter left={remaining[key]} goal={goal[key]} label={label} />
            </li>
          )
        })}
      </ul>
    </>
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
    return (
      <p className="muted">
        Nothing can be made with what is on hand. Recipes appear here once enough of their main
        ingredients are in stock.
      </p>
    )
  }
  return (
    <ol className="recommendations">
      {items.map((item, index) => {
        const missing = item.availability.ingredients.filter((i) => i.is_missing)
        const expired = item.expiry_urgency.expired_batches.length
        const recent = item.recent_frequency.times_eaten_recently
        const isOpen = openRecipeId === item.recipe_id
        return (
          <li key={item.recipe_id} className={index === 0 ? 'featured' : undefined}>
            <button
              type="button"
              className="recommendation-summary"
              aria-expanded={isOpen}
              onClick={() => setOpenRecipeId(isOpen ? null : item.recipe_id)}
            >
              <span className="rank">{index + 1}</span>
              <span className="recommendation-name">{item.name}</span>
              <span className="score" title="Score out of 100, ranked by the backend">
                {formatScore(item.score)}
              </span>
              <span className="facts">
                <span>{formatScore(item.availability.score)}% of ingredients on hand</span>
                {missing.length > 0 && (
                  <span className="flag">No {missing.map((i) => i.name.toLowerCase()).join(', ')}</span>
                )}
                {expired > 0 && (
                  <span className="flag">
                    {expired} batch{expired > 1 ? 'es' : ''} past use-by
                  </span>
                )}
                {recent > 0 && (
                  <span>
                    Eaten {recent} time{recent > 1 ? 's' : ''} this week
                  </span>
                )}
              </span>
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
    return <p className="muted">The fridge is empty. Add groceries to start getting recommendations.</p>
  }
  return (
    <ul className="inventory">
      {items.map((item) => (
        <li key={item.ingredient_id}>
          <span>{item.name}</span>
          <span className="quantity">
            {formatQuantity(item.quantity_on_hand, item.canonical_unit)}
          </span>
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
    return <p className="muted">Nothing logged yet today. Open a recipe and choose “I ate this”.</p>
  }
  return (
    <ul className="meals">
      {meals.map((meal) => (
        <li key={meal.id}>
          <span className="meal-time">{formatTime(meal.consumed_at)}</span>
          <span className="meal-name">{meal.name}</span>
          <span className="meal-kcal">{Math.round(meal.calories)} kcal</span>
          <span className="meal-rating">
            {meal.rating === null ? (
              <RateMeal meal={meal} onRated={onRated} />
            ) : (
              <span className="muted">You rated it {meal.rating} of 5</span>
            )}
          </span>
        </li>
      ))}
    </ul>
  )
}

function Dashboard() {
  // Bumped after a write so every section refetches.
  const [version, setVersion] = useState(0)
  const [notice, setNotice] = useState<string | null>(null)
  // Meals logged and groceries added from anywhere on the page: changes to the stock or the day
  // that a plan did not simulate. The planner uses it to retire an outdated plan.
  const [kitchenChanges, setKitchenChanges] = useState(0)

  const nutrition = useResource(getNutritionState, version)
  const recommendations = useResource(getRecommendations, version)
  const inventory = useResource(getInventory, version)
  const meals = useResource(getTodaysMeals, version)

  function handleMealLogged(meal: MealLog, servings: number) {
    setNotice(`Logged ${meal.name}, ${servings} serving${servings === 1 ? '' : 's'}.`)
    setVersion((current) => current + 1)
    setKitchenChanges((current) => current + 1)
  }

  // New stock changes inventory, recommendations, and any plan on screen.
  function handleGroceriesAdded(message: string) {
    setNotice(message)
    setVersion((current) => current + 1)
    setKitchenChanges((current) => current + 1)
  }

  // A rating changes the meal's row and its recipe's enjoyment score, so refetch everything.
  function handleRated(meal: MealLog, rating: number | null) {
    setNotice(
      rating === null ? `${meal.name} was already rated.` : `Rated ${meal.name} ${rating} of 5.`,
    )
    setVersion((current) => current + 1)
  }

  return (
    <>
      {notice && (
        <p className="banner success" role="status">
          {notice}
          <button type="button" className="link-button" onClick={() => setNotice(null)}>
            Dismiss
          </button>
        </p>
      )}
      <div className="dashboard">
        <div className="main-column">
          <MealPlanner kitchenChanges={kitchenChanges} onMealLogged={handleMealLogged} />
          <Section title="What to make" state={recommendations} className="shelf">
            {(items) => <RecommendationList items={items} onMealLogged={handleMealLogged} />}
          </Section>
        </div>
        <aside className="sidebar">
          <Section title="Today" state={nutrition} className="side-section">
            {(state) => <NutritionSummary state={state} />}
          </Section>
          <Section title="Eaten today" state={meals} className="side-section">
            {(items) => <MealList meals={items} onRated={handleRated} />}
          </Section>
          <Section title="In the fridge" state={inventory} className="side-section">
            {(items) => (
              <>
                <InventoryList items={items} />
                <AddGroceries onAdded={handleGroceriesAdded} />
              </>
            )}
          </Section>
        </aside>
      </div>
    </>
  )
}

export default Dashboard
