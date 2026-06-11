// File-tree favorites — shared by FileTreePanel and FilePreviewModal so that
// adding/removing from the preview reflects in the tree's favorite section
// without a reload. Persisted in localStorage (device-local).

const FAV_KEY = 'cpc.fileTree.favorites'
const EVENT = 'cpc-favorites-changed'

export function loadFavs() {
  try {
    const raw = localStorage.getItem(FAV_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed) ? parsed.filter(f => f && typeof f.path === 'string') : []
  } catch { return [] }
}

function saveFavs(favs) {
  try { localStorage.setItem(FAV_KEY, JSON.stringify(favs)) } catch { /* quota */ }
  try { window.dispatchEvent(new CustomEvent(EVENT)) } catch { /* noop */ }
}

export function isFav(path) {
  return loadFavs().some(f => f.path === path)
}

export function addFav(path, is_dir, name) {
  const favs = loadFavs()
  if (favs.some(f => f.path === path)) return favs
  const next = [...favs, { path, is_dir: !!is_dir, name: name || path.split('/').pop() || path }]
  saveFavs(next)
  return next
}

export function removeFav(path) {
  const next = loadFavs().filter(f => f.path !== path)
  saveFavs(next)
  return next
}

export function toggleFav(path, is_dir, name) {
  return isFav(path) ? removeFav(path) : addFav(path, is_dir, name)
}

export function subscribeFavs(callback) {
  const handler = () => callback(loadFavs())
  window.addEventListener(EVENT, handler)
  window.addEventListener('storage', handler)
  return () => {
    window.removeEventListener(EVENT, handler)
    window.removeEventListener('storage', handler)
  }
}
