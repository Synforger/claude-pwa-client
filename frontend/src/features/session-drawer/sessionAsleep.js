// Which tabs of the list changed between asleep and awake, according to one overview snapshot.
//
// A tab whose claude was put to sleep (backend/sleep/) shows 💤 in the list. The list rows carry `asleep` from
// GET /sessions; the overview snapshot repeats it per tab when the backend sends it, so a list that is already on
// screen follows a tab going to sleep or waking up without being reloaded. A tab the snapshot says nothing about
// keeps what its row says.

/** @param {Array<{id: string, asleep?: boolean}>} sessions the rows of the list
 *  @param {Record<string, {asleep?: boolean}>} payload one overview snapshot
 *  @returns {Array<[string, boolean]>} [tab id, asleep] for every tab whose state differs from its row */
export function asleepChanges(sessions, payload) {
  const changes = []
  for (const s of sessions) {
    const info = payload?.[s.id]
    if (!info || typeof info.asleep !== 'boolean') continue
    if (!!s.asleep !== info.asleep) changes.push([s.id, info.asleep])
  }
  return changes
}
