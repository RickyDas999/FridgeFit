import { useState, type FormEvent } from 'react'
import { addInventoryBatch, getIngredients, type CanonicalUnit, type Ingredient } from './api'
import { formatQuantity } from './format'
import { useResource } from './useResource'

// Spelled out beside the quantity input, so the unit to type in is unmistakable.
const UNIT_NAMES: Record<CanonicalUnit, string> = {
  gram: 'grams',
  milliliter: 'milliliters',
  count: 'count',
}

/**
 * The open form: choose an existing ingredient, enter how much, and optionally its use-by date.
 * Mounted only while open, so the ingredient list loads when the form opens.
 */
function GroceryForm(props: { onAdded: (message: string) => void; onCancel: () => void }) {
  const { onAdded, onCancel } = props
  const ingredients = useResource(getIngredients)
  const [ingredientId, setIngredientId] = useState('')
  const [quantity, setQuantity] = useState('')
  const [useBy, setUseBy] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  if (ingredients.status === 'loading') return <p className="muted">Loading ingredients…</p>
  if (ingredients.status === 'error') {
    return (
      <div className="add-groceries">
        <p className="error-text">{ingredients.message}</p>
        <button type="button" className="secondary" onClick={onCancel}>
          Close
        </button>
      </div>
    )
  }

  const list = ingredients.data
  const selected: Ingredient | undefined = list.find((item) => item.id === Number(ingredientId))

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    const amount = Number(quantity)
    // Usability checks only; the backend validates the request again.
    if (!selected) {
      setError('Choose an ingredient.')
      return
    }
    if (quantity.trim() === '' || !Number.isFinite(amount) || amount <= 0) {
      setError('Enter a quantity above 0.')
      return
    }
    setSubmitting(true)
    setError(null)
    try {
      await addInventoryBatch(selected.id, amount, useBy || null)
      const amountText = formatQuantity(amount, selected.canonical_unit)
      onAdded(`Added ${amountText} ${selected.name.toLowerCase()} to the fridge.`)
    } catch (failure) {
      setError((failure as Error).message)
      setSubmitting(false)
    }
  }

  if (list.length === 0) {
    return (
      <div className="add-groceries">
        <p className="muted">No ingredients exist yet; they are added through the API.</p>
        <button type="button" className="secondary" onClick={onCancel}>
          Close
        </button>
      </div>
    )
  }

  return (
    // noValidate: the checks above give clearer messages than the browser's defaults.
    <form className="add-groceries" onSubmit={handleSubmit} noValidate>
      <label>
        Ingredient
        <select
          value={ingredientId}
          disabled={submitting}
          onChange={(event) => setIngredientId(event.target.value)}
        >
          <option value="">Choose an ingredient</option>
          {list.map((item) => (
            <option key={item.id} value={item.id}>
              {item.name}
            </option>
          ))}
        </select>
      </label>
      <label>
        Quantity
        <span className="quantity-input">
          <input
            type="number"
            inputMode="decimal"
            min="0"
            step="any"
            value={quantity}
            disabled={submitting}
            onChange={(event) => setQuantity(event.target.value)}
          />
          {selected && <span className="muted">{UNIT_NAMES[selected.canonical_unit]}</span>}
        </span>
      </label>
      <label>
        Use-by date (optional)
        <input
          type="date"
          value={useBy}
          disabled={submitting}
          onChange={(event) => setUseBy(event.target.value)}
        />
      </label>
      <div className="form-actions">
        <button type="submit" disabled={submitting}>
          {submitting ? 'Adding…' : 'Add to fridge'}
        </button>
        <button type="button" className="secondary" onClick={onCancel} disabled={submitting}>
          Cancel
        </button>
      </div>
      {error && <p className="error-text">{error}</p>}
    </form>
  )
}

/** "+ Add groceries" under the fridge list: record a purchase of an existing ingredient. */
function AddGroceries({ onAdded }: { onAdded: (message: string) => void }) {
  const [open, setOpen] = useState(false)

  if (!open) {
    return (
      <button
        type="button"
        className="link-button add-groceries-toggle"
        onClick={() => setOpen(true)}
      >
        + Add groceries
      </button>
    )
  }
  return (
    <GroceryForm
      onAdded={(message) => {
        // Closing unmounts the form, which resets it; the dashboard refetches from the backend.
        setOpen(false)
        onAdded(message)
      }}
      onCancel={() => setOpen(false)}
    />
  )
}

export default AddGroceries
