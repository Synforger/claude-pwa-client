import { useState, useEffect, useCallback } from 'react'
import { loadFavs, removeFav, subscribeFavs } from './favorites.js'
import { setOverlay } from '../../state/ui.js'
import './FileTreePanel.css'

function displayShort(path) {
  return path.replace(/^\/Users\/[^/]+/, '~')
}

// ⭐ ボタンから開くポップアップ。 ファイルツリーを経由せずお気に入りだけを縦並び表示し、
// タップで dir なら FileTreePanel に、 file なら FilePreviewModal に飛ばす。
//
// W2 Phase E1: OverlayHost 経由 render に対応するため props を全廃 (= props 自己解決契約)。
// onOpenFile / onOpenDir / onClose を全部 setOverlay 直呼出に切り替え (= 旧 AppShell 内 inline
// callback を本 component 内に移送、 onClose 経路は `setOverlay('favs', false)`)。
export default function FavoritesQuickPicker() {
  const onOpenFile = useCallback((path) => setOverlay('previewPath', path), [])
  const onOpenDir = useCallback((path) => setOverlay('treeOpen', path), [])
  const onClose = useCallback(() => setOverlay('favs', false), [])
  const [favs, setFavs] = useState(() => loadFavs())
  useEffect(() => subscribeFavs(setFavs), [])

  const handleRemove = (path) => setFavs(removeFav(path))

  const handlePick = (fav) => {
    if (fav.is_dir) onOpenDir?.(fav.path)
    else onOpenFile?.(fav.path)
    onClose?.()
  }

  return (
    <div className="tree-overlay" onClick={onClose}>
      <div className="tree-panel" onClick={e => e.stopPropagation()}>
        <div className="tree-header">
          <div className="tree-nav">
            <span className="tree-path">★ お気に入り</span>
          </div>
          <button className="modal-close" onClick={onClose}>✕</button>
        </div>
        <div className="tree-body">
          {favs.length === 0 && (
            <div className="dim tree-loading">
              まだお気に入りはありません。 ファイルツリーから ☆ をタップして登録してください。
            </div>
          )}
          {favs.map(fav => (
            <div key={fav.path} className="tree-fav-entry">
              <div className="tree-fav-main" onClick={() => handlePick(fav)}>
                <span className="tree-icon">{fav.is_dir ? '📁' : '📄'}</span>
                <div className="tree-fav-text">
                  <div className="tree-fav-name">{fav.name}</div>
                  <div className="tree-fav-path">{displayShort(fav.path)}</div>
                </div>
              </div>
              <button
                className="tree-fav-remove"
                onClick={(e) => { e.stopPropagation(); handleRemove(fav.path) }}
                aria-label="remove-favorite"
              >✕</button>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
