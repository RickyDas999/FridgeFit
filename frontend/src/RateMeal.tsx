import { useState } from 'react'
import { rateMeal, type MealLog } from './api'

const RATINGS = [1, 2, 3, 4, 5]

type Props = {
  meal: MealLog
  /** Called after the backend stores the rating, or reports the meal was already rated. */
  onRated: (meal: MealLog, rating: number | null) => void
}

/**
 * One-time 1-5 rating for a logged meal, through the feedback endpoint.
 *
 * No idempotency key is needed: the backend accepts one rating per meal, so a repeated
 * submission is rejected (409) instead of stored twice. Buttons are disabled while sending.
 */
function RateMeal({ meal, onRated }: Props) {
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function submit(rating: number) {
    setSubmitting(true)
    setError(null)
    try {
      const result = await rateMeal(meal.id, rating)
      // The dashboard refetches either way, replacing these buttons with the stored rating.
      onRated(meal, result === 'rated' ? rating : null)
    } catch (failure) {
      setError((failure as Error).message)
      setSubmitting(false)
    }
  }

  return (
    <span className="rate-meal">
      <span role="group" aria-label={`Rate ${meal.name} from 1 to 5`} className="rating-buttons">
        {RATINGS.map((rating) => (
          <button
            key={rating}
            type="button"
            className="rating-button"
            disabled={submitting}
            aria-label={`${rating} out of 5`}
            onClick={() => void submit(rating)}
          >
            {rating}
          </button>
        ))}
      </span>
      {error && <span className="error-text">{error}</span>}
    </span>
  )
}

export default RateMeal
