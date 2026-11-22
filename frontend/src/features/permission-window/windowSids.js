// Which tabs have a permission window open, read off one snapshot of every tab's status. A judgment only; the list of
// tabs (SessionDrawer.jsx) marks those rows through useOpenPermissionWindows.js.

/** @param {Record<string, {pending_permission?: unknown} | null> | null | undefined} allStatus
 *  one status snapshot, keyed by tab id
 *  @returns {Set<string>} the ids of the tabs whose status carries a window */
export function sidsWithWindow(allStatus) {
  const sids = new Set()
  if (!allStatus || typeof allStatus !== 'object') return sids
  for (const [sid, status] of Object.entries(allStatus)) {
    if (status && status.pending_permission) sids.add(sid)
  }
  return sids
}
