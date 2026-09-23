import { useRef, useState, useSyncExternalStore } from 'react'
import { subscribe as subscribeUi, getSnapshot as getUiSnapshot, setOverlay } from '../../state/ui.js'
import { useOutsideClick } from '../../hooks/useOutsideClick.js'
import { useT } from '../../i18n/t.js'
import { useExtensions } from './useExtensions.js'
import { SLOT_LONG_PRESS_MS, loadLastId, nextOpenOnTap, saveLastId } from './slotTap.js'
import './ExtensionMenu.css'

// 拡張の差し口 (= 上部バーの右端の 🧩 1 個)。
// - タップ: 開いている拡張があれば畳み、 無ければ最後に開いた拡張を開く (= 判定は slotTap.js)
// - 長押し / 右クリック: 届く拡張の一覧を開き、 選んだ拡張を開く (= 開いている拡張を選ぶと畳む)
// 帯は畳んでも iframe が残る (= ExtensionHost 参照)。 拡張が何本あってもボタンは 1 個で、
// 拡張ごとの `icon` は一覧の中の見分けにだけ使う。 届く拡張が 1 本も無ければ何も出さない。
export default function ExtensionMenu() {
  const extensions = useExtensions()
  const openId = useSyncExternalStore(subscribeUi, () => getUiSnapshot().overlays.extensionOpen)
  const [listOpen, setListOpen] = useState(false)
  const [lastId, setLastId] = useState(loadLastId)
  const rootRef = useRef(null)
  const pressTimerRef = useRef(null)
  const longPressedRef = useRef(false)
  useOutsideClick(rootRef, () => setListOpen(false))
  const t = useT()
  if (extensions.length === 0) return null
  const anyOpen = extensions.some((ext) => ext.id === openId)

  const openExtension = (id) => {
    setOverlay('extensionOpen', id)
    if (id) {
      setLastId(id)
      saveLastId(id)
    }
  }
  const cancelPress = () => clearTimeout(pressTimerRef.current)
  const onPressStart = () => {
    longPressedRef.current = false
    cancelPress()
    pressTimerRef.current = setTimeout(() => {
      longPressedRef.current = true
      setListOpen(true)
    }, SLOT_LONG_PRESS_MS)
  }
  const onTap = () => {
    // 長押しで一覧を開いた直後の click は、 タップとして扱わない。
    if (longPressedRef.current) {
      longPressedRef.current = false
      return
    }
    if (listOpen) {
      setListOpen(false)
      return
    }
    openExtension(nextOpenOnTap(extensions, openId, lastId))
  }
  const onContextMenu = (e) => {
    e.preventDefault()
    cancelPress()
    setListOpen(true)
  }

  return (
    <span className="ext-menu-root" ref={rootRef}>
      <button
        className={`screen-toggle ext-slot-btn ${anyOpen ? 'active' : ''}`}
        onPointerDown={onPressStart}
        onPointerUp={cancelPress}
        onPointerLeave={cancelPress}
        onPointerCancel={cancelPress}
        onClick={onTap}
        onContextMenu={onContextMenu}
        aria-label={t('topbar.extensions')}
        title={t('topbar.extensions_hint')}
        data-testid="extension-menu-toggle"
      >
        🧩
      </button>
      {listOpen && (
        <div className="ext-menu-popup">
          {extensions.map((ext) => {
            const active = ext.id === openId
            return (
              <button
                key={ext.id}
                className={`ext-menu-item ${active ? 'active' : ''}`}
                onClick={() => { openExtension(active ? null : ext.id); setListOpen(false) }}
                title={active ? t('topbar.extension_close', { title: ext.title }) : t('topbar.extension_open', { title: ext.title })}
                data-testid={`extension-item-${ext.id}`}
              >
                <span className="ext-menu-icon">{ext.icon}</span>
                {ext.title}
              </button>
            )
          })}
        </div>
      )}
    </span>
  )
}
