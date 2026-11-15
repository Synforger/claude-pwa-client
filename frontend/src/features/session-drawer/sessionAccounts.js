// Which rows of the list show a stale account, according to one overview snapshot.
//
// A row's account label comes from `account_id` (the account the tab runs on now), `fallback_from` (the account it
// was moved off when the client moved it for a usage limit), `account_pinned` (held on its account) and, for a
// sleeping tab, `account_on_wake` (the account it runs on once woken, which the account fallback decides at that
// moment and can differ from `account_id`). The rows carry them from GET /sessions; the overview snapshot repeats
// them per tab, so a list that is already on screen follows an automatic move between accounts without being fetched
// again. A tab the snapshot says nothing about keeps what its row says.

const ACCOUNT_FIELDS = ['account_id', 'fallback_from', 'account_pinned', 'account_on_wake']

// An unset field and a null one mean the same (= the tab has no such account); a flag that is unset is false.
const normalized = (field, value) => (field === 'account_pinned' ? value === true : value ?? null)

/** @param {Array<{id: string}>} sessions the rows of the list
 *  @param {Record<string, object>} payload one overview snapshot
 *  @returns {Array<[string, object]>} [tab id, the fields to write] for every tab whose row differs from the snapshot */
export function accountChanges(sessions, payload) {
  const changes = []
  for (const s of sessions) {
    const info = payload?.[s.id]
    if (!info || typeof info !== 'object') continue
    const patch = {}
    for (const field of ACCOUNT_FIELDS) {
      if (!(field in info)) continue
      if (normalized(field, s[field]) !== normalized(field, info[field])) patch[field] = info[field] ?? null
    }
    if (Object.keys(patch).length > 0) changes.push([s.id, patch])
  }
  return changes
}

/** The account label of a row, null where no label shows (= with one account configured every row would say the same).
 *  A sleeping tab shows the account it runs on once woken, and the one it last ran on in brackets when the two differ.
 *  @param {{account_id?: string|null, account_on_wake?: string|null}} session the row
 *  @param {Array<{id: string, display_name?: string}>} accounts the configured accounts
 *  @param {string|null} defaultAccountId the account a row with no `account_id` runs on
 *  @param {(key: string, params?: object) => string} t the translation function
 *  @returns {string|null} */
export function accountLabelOf(session, accounts, defaultAccountId, t) {
  if (accounts.length <= 1) return null
  const nameOf = (id) => accounts.find((a) => a.id === id)?.display_name || id || null
  const last = session.account_id || defaultAccountId
  const onWake = session.account_on_wake
  if (onWake && onWake !== last) {
    return `${nameOf(onWake)} (${t('drawer.account.asleep_last', { account: nameOf(last) })})`
  }
  return nameOf(last)
}
