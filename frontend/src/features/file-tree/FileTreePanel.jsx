import { useState, useEffect, useCallback } from 'react'
import { apiFetch } from '../../utils/api.js'
import { loadFavs, toggleFav as toggleFavStore, removeFav as removeFavStore, subscribeFavs } from './favorites.js'
import { lsSetDebounced } from '../../utils/storage.js'
import './FileTreePanel.css'

const HOME = '~'

function displayShort(path) {
  return path.replace(/^\/Users\/[^/]+/, '~')
}

function parentPath(p) {
  if (!p || p === '~' || p === '/') return null
  // HOME (= REDACTED_PATH) は `~` と等価。 backend は HOME 外を 403 で弾くので、
  // これ以上遡ろうとすると「読み込みエラー」 が出てしまう。
  if (/^\/Users\/[^/]+\/?$/.test(p)) return null
  // backend が解決済みの絶対 path も `~` 起点の表示も両方扱う
  const trimmed = p.replace(/\/+$/, '')
  const idx = trimmed.lastIndexOf('/')
  if (idx < 0) return null
  const parent = trimmed.slice(0, idx)
  if (parent === '' || parent === '~') return '~'
  return parent
}

export default function FileTreePanel({ onOpenFile, onClose, initialPath }) {
  const [currentPath, setCurrentPath] = useState(initialPath || HOME)
  const [entries, setEntries] = useState([])
  const [history, setHistory] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [favs, setFavs] = useState(() => loadFavs())
  // 永続化形式: lsSetDebounced は JSON で書く → 旧 raw string '0' / '1' との両方を読む。
  // boolean を JSON 化 (= "true" / "false") した値も認識する。 default = true (= 開く)。
  const [favsOpen, setFavsOpen] = useState(() => {
    try {
      const raw = localStorage.getItem('cpc.fileTree.favsOpen')
      if (raw == null) return true
      // 旧 raw 形式: '0' / '1'
      if (raw === '0') return false
      if (raw === '1') return true
      // 新 JSON 形式: 'true' / 'false'
      try { return JSON.parse(raw) !== false } catch { return true }
    } catch { return true }
  })
  // 連打しても末尾値だけ commit する debounce 化 (= F-46)。 単発操作だが pagehide で
  // 確実に書き戻すので「閉じたまま閉じる」 系の取りこぼしも防げる。 lsSetDebounced は
  // JSON.stringify するので '1'/'0' は JSON string として保存される (= 既存 raw 値とは
  // 形式が違う)。 read 側はそのまま `!== '0'` で raw 比較しており「`"0"` (JSON) も `0` も
  // 一致しない = true」 になるので、 単に boolean を直接保存して読み側もそれに合わせる。
  const toggleFavsOpen = () => {
    setFavsOpen(prev => {
      const next = !prev
      lsSetDebounced('cpc.fileTree.favsOpen', next)
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
    // 履歴があれば pop、 無くてもルート (~) より上でなければ親へ移動する
    // (= お気に入りから initialPath で開いた時も親へ遡れる)。
    if (history.length > 0) {
      const prev = history[history.length - 1]
      setHistory(h => h.slice(0, -1))
      loadDir(prev)
      return
    }
    const parent = parentPath(currentPath)
    if (parent && parent !== currentPath) loadDir(parent)
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
    <div className="tree-overlay" onClick={onClose} data-testid="file-tree-modal">
      <div className="tree-panel" onClick={e => e.stopPropagation()}>
        <div className="tree-header">
          <div className="tree-nav">
            <button
              className="tree-back"
              onClick={handleBack}
              disabled={history.length === 0 && !parentPath(currentPath)}
            >←</button>
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
