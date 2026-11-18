// Which API tab rows of the list are stale, according to one overview snapshot.
//
// An API tab's row shows its title and how much of the context its conversation holds (`context_tokens`, and
// `context_window` when the program that lists the tab says its size; `kind: "api"`, the program outside the client
// writes the conversation, `backend/api_tabs/`). The rows carry them from GET /sessions; the overview snapshot repeats
// them per API tab, so a list that is already on screen follows them without being fetched again (the same way it
// follows an account change, `sessionAccounts.js`). Only an API tab's snapshot entry has `context_tokens`; a tab the
// snapshot says nothing about keeps its row.

/** The figures an API tab's row and its snapshot entry carry (a title the entry leaves out is not compared). */
const CONTEXT_KEYS = ['context_tokens', 'context_window']

/** @param {Array<{id: string, title?: string, context_tokens?: number|null, context_window?: number|null}>} sessions
 *    the rows of the list
 *  @param {Record<string, {title?: string, context_tokens?: number|null, context_window?: number|null}>} payload one
 *    overview snapshot
 *  @returns {Array<[string, object]>} [tab id, the fields to put on its row] for every API tab whose row differs */
export function apiRowChanges(sessions, payload) {
  const changes = []
  for (const s of sessions) {
    const info = payload?.[s.id]
    if (!info || typeof info !== 'object' || !('context_tokens' in info)) continue
    const fields = Object.fromEntries(CONTEXT_KEYS.map(key => [key, info[key] ?? null]))
    if (typeof info.title === 'string' && info.title) fields.title = info.title
    if (Object.keys(fields).some(key => (s[key] ?? null) !== fields[key])) changes.push([s.id, fields])
  }
  return changes
}
