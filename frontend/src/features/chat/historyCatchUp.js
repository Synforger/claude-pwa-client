// Fetches a tab's history from the backend and applies it to the screen (called by useChatStream).
//
// The screen lays the backend's history over its own cache (the messages in memory and the copy
// saved in localStorage), matching by uuid. When the screen stayed closed while more lines were
// written than the backend's window holds, the cache and the window leave a hole between them.
// The backend says whether the window reached the line right after the screen's position (`since`)
// with `reached`; when it did not, the cache is dropped and the screen is rebuilt from the
// returned events alone.
import { apiFetch } from '../../_common/api.js'
import { LS_MESSAGES_V2_PREFIX } from '../../_common/constants.js'

/** Path of the history request. `since` (the screen's offset for the tab) is left out when unknown; 0 is a valid position. */
export function historyPath(sid, since) {
  const base = `/jsonl/history/${encodeURIComponent(sid)}`
  return Number.isFinite(since) && since >= 0 ? `${base}?since=${Math.floor(since)}` : base
}

/** Fetches the history as `{ events, pos, reached }`; null when it could not be fetched (the stream replay fills in). */
export async function fetchHistory(sid, since) {
  try {
    const response = await apiFetch(historyPath(sid, since))
    if (!response || !response.ok) return null
    const data = await response.json().catch(() => null)
    return data && Array.isArray(data.events) ? data : null
  } catch {
    return null
  }
}

/** Removes the copy of the tab's messages saved in localStorage. */
export function removeSavedMessages(sid) {
  try { localStorage.removeItem(LS_MESSAGES_V2_PREFIX + sid) } catch { /* storage unavailable */ }
}

/**
 * Applies fetched history to the screen; returns whether the cache was dropped.
 *
 * - `reached === false`: dropCache(sid) runs before any event is applied, so the screen is rebuilt
 *   from the returned events alone. A response without `reached` (an older backend) cannot say
 *   whether anything is missing, so the cache is kept.
 * - dropWhenNotReached false: the cache is kept (the caller already dropped it).
 * - Events go to ingest(event) one by one; applying stops once isCancelled() is true.
 */
export function ingestHistory(data, { sid, dropCache, ingest, isCancelled = () => false, dropWhenNotReached = true }) {
  const shouldDrop = dropWhenNotReached && data.reached === false
  if (shouldDrop) dropCache(sid)
  for (const event of data.events) {
    if (isCancelled()) break
    ingest(event)
  }
  return shouldDrop
}
