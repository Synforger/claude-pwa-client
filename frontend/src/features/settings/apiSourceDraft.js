// The settings card of a program that lists API tabs (`ApiSourceCard.jsx`): the input it holds and what it sends.
// The fields are the program's own (its tab list file declares them, `backend/api_tabs/`), so nothing here knows their
// names: each field says its range and grid, and a value is checked the way the backend checks it before it writes.

/** How far a value may sit from the grid of `step` and still be on it (= `api_source_settings_values.STEP_TOLERANCE`). */
const STEP_TOLERANCE = 1e-9

/** The input of the card: each field's value as text. */
export function sourceDraftOf(source) {
  return Object.fromEntries(source.fields.map(field => [field.key, String(source.values?.[field.key] ?? field.default)]))
}

/** The number a text holds (decimals and a sign allowed), null when it holds none. */
function numberOf(text) {
  const trimmed = String(text).trim()
  if (!/^-?\d+(\.\d+)?$/.test(trimmed)) return null
  return Number(trimmed)
}

function onGrid(value, field) {
  if (field.step === null || field.step === undefined) return true
  const steps = (value - field.min) / field.step
  return Math.abs(steps - Math.round(steps)) <= STEP_TOLERANCE * Math.max(1, Math.abs(steps))
}

/** @returns {{values: Record<string, number>|null, invalid: string[]}} the values that changed (null when none) and the
 *    keys whose text is not a value the field takes */
export function sourcePatch(source, draft) {
  const values = {}
  const invalid = []
  for (const field of source.fields) {
    const value = numberOf(draft[field.key] ?? '')
    if (value === null || value < field.min || value > field.max || !onGrid(value, field)) {
      invalid.push(field.key)
      continue
    }
    const now = source.values?.[field.key] ?? field.default
    if (value !== now) values[field.key] = value
  }
  return { values: Object.keys(values).length ? values : null, invalid }
}
