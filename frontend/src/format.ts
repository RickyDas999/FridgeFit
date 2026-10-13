import type { CanonicalUnit } from './api'

// Display formatting only: rounding and labels for values the API already computed.

const UNIT_LABELS: Record<CanonicalUnit, string> = { gram: 'g', milliliter: 'ml', count: '' }

/** Format a quantity with its unit, e.g. "450 g" or "6"; no unit when it is not known. */
export function formatQuantity(quantity: number, unit?: CanonicalUnit): string {
  const rounded = Math.round(quantity * 10) / 10
  const label = unit ? UNIT_LABELS[unit] : ''
  return label ? `${rounded} ${label}` : `${rounded}`
}

/** Format a 0-1 score from the API as a whole number out of 100. */
export function formatScore(score: number): string {
  return `${Math.round(score * 100)}`
}

/** Format a local, timezone-less ISO datetime from the API as a time of day, e.g. "08:00". */
export function formatTime(isoDateTime: string): string {
  return new Date(isoDateTime).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

/**
 * Format an API calendar date ("YYYY-MM-DD"), e.g. "Oct 11".
 *
 * Built from its parts because `new Date("YYYY-MM-DD")` means UTC midnight, which shows as the
 * previous day in timezones behind UTC.
 */
export function formatDate(isoDate: string): string {
  const [year, month, day] = isoDate.split('-').map(Number)
  return new Date(year, month - 1, day).toLocaleDateString([], { month: 'short', day: 'numeric' })
}
