import { useCallback } from 'react'
import { getRecipe, type Recommendation } from './api'
import { formatDate, formatQuantity, formatScore } from './format'
import { useResource } from './useResource'

/**
 * Explain one recommendation using only what the API returned.
 *
 * Every score and quantity shown here comes from GET /recommendations or GET /recipes/{id};
 * nothing is recalculated. The backend's ranking weights are deliberately not repeated here.
 */
function RecommendationDetail({ recommendation }: { recommendation: Recommendation }) {
  const { recipe_id, availability, expiry_urgency, macro_fit, enjoyment, recent_frequency } =
    recommendation
  const loadRecipe = useCallback(() => getRecipe(recipe_id), [recipe_id])
  const recipe = useResource(loadRecipe)

  // Units and names for display, from the recipe response (availability items carry no unit).
  const recipeLines = recipe.status === 'ready' ? recipe.data.ingredients : []
  const unitOf = (ingredientId: number) =>
    recipeLines.find((line) => line.ingredient_id === ingredientId)?.canonical_unit
  const nameOf = (ingredientId: number) =>
    availability.ingredients.find((item) => item.ingredient_id === ingredientId)?.name ??
    `Ingredient ${ingredientId}`

  const components = [
    { label: 'Availability', value: formatScore(availability.score) },
    { label: 'Expiry urgency', value: formatScore(expiry_urgency.score) },
    { label: 'Macro fit', value: macro_fit ? formatScore(macro_fit.score) : 'No goal' },
    { label: 'Enjoyment', value: formatScore(enjoyment.score) },
  ]

  return (
    <div className="recommendation-detail">
      <h3>Why it ranks here</h3>
      <dl className="component-scores">
        {components.map(({ label, value }) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>
      <p className="detail">
        Scores are out of 100 and combined by the backend into this recipe's score of{' '}
        {formatScore(recommendation.score)}.
      </p>

      <h3>Ingredients for one serving</h3>
      <ul className="plain-list">
        {availability.ingredients.map((item) => {
          const unit = unitOf(item.ingredient_id)
          return (
            <li key={item.ingredient_id}>
              <span>
                {item.name} <span className="detail">({item.role})</span>
              </span>
              <span className="ingredient-status">
                <span className="detail">
                  have {formatQuantity(item.quantity_on_hand, unit)} · need{' '}
                  {formatQuantity(item.quantity_per_serving, unit)}
                </span>
                {item.is_missing ? (
                  <span className="tag warn">Missing</span>
                ) : (
                  item.fraction_available < 1 && (
                    <span className="tag warn">
                      Short ({formatScore(item.fraction_available)}%)
                    </span>
                  )
                )}
              </span>
            </li>
          )
        })}
      </ul>

      {expiry_urgency.expired_batches.length > 0 && (
        <>
          <h3>Past use-by date</h3>
          <ul className="plain-list">
            {expiry_urgency.expired_batches.map((batch) => (
              <li key={batch.batch_id}>
                <span className="warn-text">{nameOf(batch.ingredient_id)}</span>
                <span className="detail">use by {formatDate(batch.use_by_date)}</span>
              </li>
            ))}
          </ul>
          <p className="detail">
            Expired food still counts as on hand; whether to use it is your call.
          </p>
        </>
      )}

      <h3>History</h3>
      <p className="detail">
        {enjoyment.rating_count === 0 || enjoyment.average_rating === null
          ? 'Not rated yet.'
          : `Rated ${enjoyment.average_rating.toFixed(1)}/5 over ${enjoyment.rating_count} meal${
              enjoyment.rating_count > 1 ? 's' : ''
            }.`}{' '}
        {recent_frequency.last_eaten_on === null
          ? 'Never eaten.'
          : `Eaten ${recent_frequency.times_eaten_recently}× in the last 7 days; last on ${formatDate(
              recent_frequency.last_eaten_on,
            )}.`}
      </p>

      <h3>Recipe</h3>
      {recipe.status === 'loading' && <p className="detail">Loading recipe…</p>}
      {recipe.status === 'error' && <p className="error-text">{recipe.message}</p>}
      {recipe.status === 'ready' && (
        <>
          <p className="detail">
            {recipe.data.prep_minutes} min · makes {recipe.data.servings} serving
            {recipe.data.servings > 1 ? 's' : ''} · per serving{' '}
            {Math.round(recipe.data.macros_per_serving.calories)} kcal,{' '}
            {Math.round(recipe.data.macros_per_serving.protein)} g protein,{' '}
            {Math.round(recipe.data.macros_per_serving.carbs)} g carbs,{' '}
            {Math.round(recipe.data.macros_per_serving.fat)} g fat
          </p>
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
