// File-tree favorites — shared by FileTreePanel, FilePreviewModal and the ⭐ quick picker.
//
// The list lives on the host (= GET / POST / DELETE /favorites, one path per line in the
// user's favorites.txt), so every device and every URL shows the same list, and the browser
// clearing its storage loses nothing. The agent can add to it by appending a line to that file.
//
// Here we only keep the last list the host sent. A change is shown at once and settled by the
// host's answer; a view that opens takes the list again, so lines added from elsewhere show up.
import { apiFetch } from '../../utils/api.js'

// Where the list used to live (= this browser only). Read once to carry it over, then removed.
const LEGACY_KEY = 'cpc.fileTree.favorites'

let favs = []
const listeners = new Set()

function setFavs(next) {
  favs = next
  listeners.forEach(cb => cb(favs))
}

async function request(path, options) {
  const res = await apiFetch(path, options)
  if (!res.ok) throw new Error(`favorites: ${res.status}`)
  const body = await res.json()
  return Array.isArray(body?.favorites) ? body.favorites : []
}

const postFav = (path) => request('/favorites', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ path }),
})

// Carry the list this browser kept over to the host, then drop the local copy. Adding is
// idempotent on the host, so several devices doing this end up with the union of their lists.
// The local copy is removed only after every entry went through.
async function carryOverLegacy() {
  let legacy = []
  try {
    const parsed = JSON.parse(localStorage.getItem(LEGACY_KEY) || '[]')
    if (Array.isArray(parsed)) legacy = parsed.filter(f => f && typeof f.path === 'string')
  } catch { /* unreadable: nothing to carry */ }
  for (const fav of legacy) await postFav(fav.path)
  try { localStorage.removeItem(LEGACY_KEY) } catch { /* storage unavailable */ }
}

let carried = null
// Changes still on their way to the host. While there are any, the list on screen is ahead of
// the host's, so an answer is applied only when it is the answer to the last of them.
let pending = 0
let queue = Promise.resolve()

function send(run) {
  pending += 1
  queue = queue.then(run).then(
    (list) => { pending -= 1; if (pending === 0) setFavs(list) },
    () => { pending -= 1; if (pending === 0) refreshFavs() },
  )
}

export async function refreshFavs() {
  try {
    if (!carried) carried = carryOverLegacy()
    await carried
  } catch {
    carried = null // the host was unreachable: try again on the next refresh
  }
  try {
    const list = await request('/favorites')
    if (pending === 0) setFavs(list)
  } catch { /* keep the list we have */ }
}

export function loadFavs() {
  return favs
}

export function isFav(path) {
  return favs.some(f => f.path === path)
}

export function addFav(path, is_dir, name) {
  if (isFav(path)) return favs
  setFavs([...favs, { path, is_dir: !!is_dir, name: name || path.split('/').pop() || path }])
  send(() => postFav(path))
  return favs
}

export function removeFav(path) {
  if (!isFav(path)) return favs
  setFavs(favs.filter(f => f.path !== path))
  send(() => request(`/favorites?path=${encodeURIComponent(path)}`, { method: 'DELETE' }))
  return favs
}

export function toggleFav(path, is_dir, name) {
  return isFav(path) ? removeFav(path) : addFav(path, is_dir, name)
}

// A view subscribes while it is open; opening is also when the list is taken from the host again.
export function subscribeFavs(callback) {
  listeners.add(callback)
  refreshFavs()
  return () => { listeners.delete(callback) }
}

// Test seam: forget everything this module remembers.
export function _resetFavsForTest() {
  favs = []
  carried = null
  pending = 0
  queue = Promise.resolve()
  listeners.clear()
}
