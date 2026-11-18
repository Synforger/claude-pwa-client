// Which rows of the list show a stale context amount, according to one overview snapshot.
//
// An API tab's row shows how much of the context its conversation holds (`context_tokens`; `kind: "api"`, the program
// outside the client writes the conversation, `backend/api_tabs/`). The rows carry it from GET /sessions; the overview
// snapshot repeats it per tab, so a list that is already on screen follows the amount without being fetched again (the
// same way it follows an account change, `sessionAccounts.js`). A tab the snapshot says nothing about keeps its row.

/** @param {Array<{id: string, context_tokens?: number|null}>} sessions the rows of the list
 *  @param {Record<string, {context_tokens?: number|null}>} payload one overview snapshot
 *  @returns {Array<[string, number|null]>} [tab id, amount] for every tab whose row differs from the snapshot */
export function contextChanges(sessions, payload) {
  const changes = []
  for (const s of sessions) {
    const info = payload?.[s.id]
    if (!info || typeof info !== 'object' || !('context_tokens' in info)) continue
    const amount = info.context_tokens ?? null
    if ((s.context_tokens ?? null) !== amount) changes.push([s.id, amount])
  }
  return changes
}
