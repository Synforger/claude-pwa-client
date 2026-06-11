import { useState, useEffect, useCallback } from 'react'
import { apiFetch } from './utils/api.js'
import { loadFavs, toggleFav as toggleFavStore, removeFav as removeFavStore, subscribeFavs } from './utils/favorites.js'
import './FileTreePanel.css'

const HOME = '~'

function displayShort(path) {
  return path.replace(/^\/Users\/[^/]+/, '~')
}

export default function FileTreePanel({ onOpenFile, onClose, initialPath }) {
  const [currentPath, setCurrentPath] = useState(initialPath || HOME)
  const [entries, setEntries] = useState([])
  const [history, setHistory] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [favs, setFavs] = useState(() => loadFavs())
  const [favsOpen, setFavsOpen] = useState(() => {
    try { return localStorage.getItem('cpc.fileTree.favsOpen') !== '0' } catch { return true }
  })
  const toggleFavsOpen = () => {
    setFavsOpen(prev => {
      const next = !prev
      try { localStorage.setItem('cpc.fileTree.favsOpen', next ? '1' : '0') } catch { /* noop */ }
      return next
    })
  }

  const loadDir = useCallback((path) => {
    setLoading(true)
    setError(null)
    apiFetch(`/files/tree?path=${encodeURIComponent(path)}`)
      .then(r => r.ok ? r.json() : Promise.reject(r.status))
      .then(data => {
        setCurrentPath(data.path)
        setEntries(data.entries)
      })
      .catch(e => setError(`読み込みエラー (${e})`))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    setHistory([])
    loadDir(initialPath || HOME)
  }, [initialPath, loadDir])

  const handleEntry = (entry) => {
    if (entry.is_dir) {
      setHistory(prev => [...prev, currentPath])
      loadDir(entry.path)
    } else {
      onOpenFile(entry.path)
    }
  }

  const handleBack = () => {
    if (history.length === 0) return
    const prev = history[history.length - 1]
    setHistory(h => h.slice(0, -1))
    loadDir(prev)
  }

  useEffect(() => subscribeFavs(setFavs), [])

  const isFav = (path) => favs.some(f => f.path === path)
  const toggleFav = (path, is_dir, name) => setFavs(toggleFavStore(path, is_dir, name))
  const removeFav = (path) => setFavs(removeFavStore(path))

  const openFav = (fav) => {
    if (fav.is_dir) {
      setHistory(prev => [...prev, currentPath])
      loadDir(fav.path)
    } else {
      onOpenFile(fav.path)
    }
  }

  const displayPath = displayShort(currentPath)
  const currentIsFav = isFav(currentPath)

  return (
    <div className="tree-overlay" onClick={onClose}>
      <div className="tree-panel" onClick={e => e.stopPropagation()}>
        <div className="tree-header">
          <div className="tree-nav">
            <button className="tree-back" onClick={handleBack} disabled={history.length === 0}>←</button>
            <span className="tree-path">{displayPath}</span>
          </div>
          <button
            className={`tree-fav-toggle ${currentIsFav ? 'on' : ''}`}
            onClick={() => toggleFav(currentPath, true, displayPath.split('/').filter(Boolean).pop() || currentPath)}
            title={currentIsFav ? 'お気に入りから削除' : 'お気に入りに登録'}
            aria-label="favorite-current"
          >{currentIsFav ? '★' : '☆'}</button>
          <button className="modal-close" onClick={onClose}>✕</button>
        </div>
        {favs.length > 0 && (
          <div className={`tree-favs ${favsOpen ? 'open' : 'closed'}`}>
            <button
              type="button"
              className="tree-favs-label"
              onClick={toggleFavsOpen}
              aria-expanded={favsOpen}
            >
              <span className="tree-favs-chev">{favsOpen ? '▼' : '▶'}</span>
              <span>★ お気に入り</span>
              <span className="tree-favs-count">{favs.length}</span>
            </button>
            {favsOpen && (
              <div className="tree-favs-list">
                {favs.map(fav => (
                  <div key={fav.path} className="tree-fav-entry">
                    <div className="tree-fav-main" onClick={() => openFav(fav)}>
                      <span className="tree-icon">{fav.is_dir ? '📁' : '📄'}</span>
                      <div className="tree-fav-text">
                        <div className="tree-fav-name">{fav.name}</div>
                        <div className="tree-fav-path">{displayShort(fav.path)}</div>
                      </div>
                    </div>
                    <button
                      className="tree-fav-remove"
                      onClick={(e) => { e.stopPropagation(); removeFav(fav.path) }}
                      aria-label="remove-favorite"
                    >✕</button>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
        <div className="tree-body">
          {loading && <span className="dim tree-loading">読み込み中...</span>}
          {error && <span className="error tree-loading">{error}</span>}
          {entries.map(entry => {
            const favored = isFav(entry.path)
            return (
              <div
                key={entry.path}
                className={`tree-entry ${entry.is_dir ? 'dir' : 'file'}`}
                onClick={() => handleEntry(entry)}
              >
                <span className="tree-icon">{entry.is_dir ? '📁' : '📄'}</span>
                <span className="tree-name">{entry.name}</span>
                <button
                  className={`tree-fav-row ${favored ? 'on' : ''}`}
                  onClick={(e) => { e.stopPropagation(); toggleFav(entry.path, entry.is_dir, entry.name) }}
                  aria-label="favorite-entry"
                >{favored ? '★' : '☆'}</button>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
