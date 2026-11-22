// What the permission window shows for one `agent_status.pending_permission`: the input in full, whether the guard
// rewrote it, and the "k / N" position. A judgment only: it reads no state and draws nothing, so a test calls it
// directly. Used by PermissionWindowDialog.jsx.

/** @typedef {{name: string | null, text: string}} InputField one part of a tool input, shown in full */

/** A string is shown as it is (a command keeps its line breaks); anything else as indented JSON.
 *  @param {unknown} value
 *  @returns {string} */
function fieldText(value) {
  if (typeof value === 'string') return value
  return JSON.stringify(value, null, 2) ?? String(value)
}

/** Split a tool input into the parts the window prints one under another, nothing cut off.
 *  A plain string is one part without a name; an object is one part per key, in its own order.
 *  @param {unknown} input the tool input as the hook received it (or the record's)
 *  @returns {InputField[]} */
export function inputFields(input) {
  if (input == null) return []
  if (typeof input !== 'object' || Array.isArray(input)) return [{ name: null, text: fieldText(input) }]
  return Object.entries(input).map(([name, value]) => ({ name, text: fieldText(value) }))
}

/** True when the input the record holds differs from the one that runs, which is what a guard's rewrite leaves.
 *  The backend sends `record_input: null` when they are the same.
 *  @param {{record_input?: unknown}} pending */
function isRewritten(pending) {
  return pending.record_input != null
}

/**
 * @param {{tool_name?: string, input?: unknown, record_input?: unknown, index?: number, count?: number}} pending
 * @returns {{toolName: string, running: InputField[], original: InputField[] | null, position: {index: number, count: number} | null}}
 *   `original` is the record's input when the guard rewrote it, else null. `position` is null unless two windows or
 *   more are queued.
 */
export function windowView(pending) {
  const count = Number.isInteger(pending.count) ? pending.count : 1
  const index = Number.isInteger(pending.index) ? pending.index : 1
  return {
    toolName: pending.tool_name || '',
    running: inputFields(pending.input),
    original: isRewritten(pending) ? inputFields(pending.record_input) : null,
    position: count >= 2 ? { index, count } : null,
  }
}
