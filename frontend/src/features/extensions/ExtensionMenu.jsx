import { useRef, useState, useSyncExternalStore } from 'react'
import { subscribe as subscribeUi, getSnapshot as getUiSnapshot, setOverlay } from '../../state/ui.js'
import { useOutsideClick } from '../../hooks/useOutsideClick.js'
import { useT } from '../../i18n/t.js'
import { useExtensions } from './useExtensions.js'
import './ExtensionMenu.css'

// 拡張の差し口 (= 上部バーの右端の 🧩 1 個)。 押すと届く拡張の一覧が開き、 選んだ拡張がチャットの
// 上の帯に出る (= 開いている拡張をもう一度選ぶと畳む、 iframe は残る = ExtensionHost 参照)。
// 拡張が何本あってもボタンは 1 個で、 拡張ごとの `icon` は一覧の中の見分けにだけ使う。
// 届く拡張が 1 本も無ければ何も出さない (= 一般の利用者には存在しない)。
export default function ExtensionMenu() {
  const extensions = useExtensions()
  const openId = useSyncExternalStore(subscribeUi, () => getUiSnapshot().overlays.extensionOpen)
  const [listOpen, setListOpen] = useState(false)
  const rootRef = useRef(null)
  useOutsideClick(rootRef, () => setListOpen(false))
  const t = useT()
  if (extensions.length === 0) return null
  const anyOpen = extensions.some((ext) => ext.id === openId)
  return (
    <span className="ext-menu-root" ref={rootRef}>
      <button
        className={`screen-toggle ${anyOpen ? 'active' : ''}`}
        onClick={() => setListOpen((v) => !v)}
        aria-label={t('topbar.extensions')}
        title={t('topbar.extensions')}
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
                onClick={() => { setOverlay('extensionOpen', active ? null : ext.id); setListOpen(false) }}
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
