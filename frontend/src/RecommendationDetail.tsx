import { useCallback } from 'react'
import { getRecipe, type MealLog, type Recommendation } from './api'
import { formatDate, formatQuantity, formatScore, formatUseBy } from './format'
import LogMeal from './LogMeal'
import { useResource } from './useResource'

/**
 * Explain one recommendation using only what the API returned.
 *
 * Every score and quantity shown here comes from GET /recommendations or GET /recipes/{id};
 * nothing is recalculated. The backend's ranking weights are deliberately not repeated here.
 */
function RecommendationDetail(props: {
  recommendation: Recommendation
  onMealLogged: (meal: MealLog, servings: number) => void
}) {
  const { recommendation, onMealLogged } = props
  const { recipe_id, availability, expiry_urgency, macro_fit, enjoyment, recent_frequency } =
    recommendation
  const loadRecipe = useCallback(() => getRecipe(recipe_id), [recipe_id])
  const recipe = useResource(loadRecipe)

  // Units and names for display, from the recipe response (availability items carry no unit).
  const recipeLines = recipe.status === 'ready' ? recipe.data.ingredients : []
  const unitOf = (ingredientId: number) =>
    recipeLines.find((line) => line.ingredient_id === ingredientId)?.canonical_unit
  const useByOf = (ingredientId: number) =>
    expiry_urgency.ingredients.find((item) => item.ingredient_id === ingredientId)
  const nameOf = (ingredientId: number) =>
    availability.ingredients.find((item) => item.ingredient_id === ingredientId)?.name ??
    `Ingredient ${ingredientId}`

  const components = [
    { label: 'Availability', value: formatScore(availability.score) },
    { label: 'Expiry urgency', value: formatScore(expiry_urgency.score) },
    { label: 'Macro fit', value: macro_fit ? formatScore(macro_fit.score) : 'No goal' },
    { label: 'Enjoyment', value: formatScore(enjoyment.score) },
  ]

  const ratingText =
    enjoyment.rating_count === 0 || enjoyment.average_rating === null
      ? 'Not rated yet.'
      : `Rated ${enjoyment.average_rating.toFixed(1)} of 5 across ${enjoyment.rating_count} meal${
          enjoyment.rating_count > 1 ? 's' : ''
        }.`
  const { times_eaten_recently: recent, last_eaten_on: lastEaten } = recent_frequency
  const eatenText =
    lastEaten === null
      ? 'You have not made it before.'
      : recent === 0
        ? `Last eaten ${formatDate(lastEaten)}.`
        : `Eaten ${recent} time${recent === 1 ? '' : 's'} in the last 7 days, most recently ${formatDate(lastEaten)}.`

  return (
    <div className="recommendation-detail">
      <LogMeal
        recipeId={recipe_id}
        recipeName={recommendation.name}
        unitOf={unitOf}
        onLogged={onMealLogged}
      />

      <h3>Why it ranks here</h3>
      <dl className="component-scores">
        {components.map(({ label, value }) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>
      <p className="muted">
        Each part is scored out of 100. The backend weighs them into the overall score of{' '}
        {formatScore(recommendation.score)}. Expiry urgency favors food that's about to expire;
        food already past its date doesn't count.
      </p>

      <h3>For one serving</h3>
      <table className="ingredients">
        <thead>
          <tr>
            <th scope="col">Ingredient</th>
            <th scope="col">Need</th>
            <th scope="col">Have</th>
            <th scope="col">Use by</th>
          </tr>
        </thead>
        <tbody>
          {availability.ingredients.map((item) => {
            const unit = unitOf(item.ingredient_id)
            const useBy = useByOf(item.ingredient_id)
            return (
              <tr key={item.ingredient_id}>
                <th scope="row">
                  {item.name}
                  <span className="role">{item.role}</span>
                </th>
                <td>{formatQuantity(item.quantity_per_serving, unit)}</td>
                <td>
                  {formatQuantity(item.quantity_on_hand, unit)}
                  {item.is_missing ? (
                    <span className="flag">None</span>
                  ) : (
                    item.fraction_available < 1 && (
                      <span className="flag">{formatScore(item.fraction_available)}% of need</span>
                    )
                  )}
                </td>
                <td className={useBy?.expiring_soon ? 'use-by soon' : 'use-by'}>
                  {useBy?.use_by_date ? formatUseBy(useBy.use_by_date) : '–'}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>

      {expiry_urgency.expired_batches.length > 0 && (
        <>
          <h3>Past its use-by date</h3>
          <ul className="expired">
            {expiry_urgency.expired_batches.map((batch) => (
              <li key={batch.batch_id}>
                {nameOf(batch.ingredient_id)}, use by {formatDate(batch.use_by_date)}
              </li>
            ))}
          </ul>
          <p className="muted">
            Expired food still counts as on hand. Whether to use it is your call.
          </p>
        </>
      )}

      <h3>History</h3>
      <p>
        {ratingText} {eatenText}
      </p>

      <h3>Recipe</h3>
      {recipe.status === 'loading' && <p className="muted">Loading recipe…</p>}
      {recipe.status === 'error' &&
        (recipe.offline ? (
          <p className="muted">Waiting for the API…</p>
        ) : (
          <p className="error-text">{recipe.message}</p>
        ))}
      {recipe.status === 'ready' && (
        <>
          <dl className="recipe-facts">
            <div>
              <dt>Prep</dt>
              <dd>{recipe.data.prep_minutes} min</dd>
            </div>
            <div>
              <dt>Makes</dt>
              <dd>
                {recipe.data.servings} serving{recipe.data.servings > 1 ? 's' : ''}
              </dd>
            </div>
            <div>
              <dt>Per serving</dt>
              <dd>
                {Math.round(recipe.data.macros_per_serving.calories)} kcal,{' '}
                {Math.round(recipe.data.macros_per_serving.protein)} g protein,{' '}
                {Math.round(recipe.data.macros_per_serving.carbs)} g carbs,{' '}
                {Math.round(recipe.data.macros_per_serving.fat)} g fat
              </dd>
            </div>
          </dl>
          {recipe.data.instructions.length > 0 && (
            <ol className="instructions">
              {recipe.data.instructions.map((step, index) => (
                <li key={index}>{step}</li>
              ))}
            </ol>
          )}
        </>
      )}
    </div>
  )
}

export default RecommendationDetail
