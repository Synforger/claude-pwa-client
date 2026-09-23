import { useState, useSyncExternalStore } from 'react'
import { subscribe as subscribeUi, getSnapshot as getUiSnapshot } from '../../state/ui.js'
import { useT } from '../../i18n/t.js'
import { useExtensions } from './useExtensions.js'
import './ExtensionHost.css'

// 拡張の枠 (= チャットの上の帯)。 Layout が Topbar の直後に常時 mount する。
//
// 一度開いた拡張の iframe は閉じても破棄せず畳むだけにする (= 閉じた瞬間に拡張の音や接続が
// 切れないように)。 破棄されるのは PWA の再読込の時だけ。 そのため overlayRegistry には載せない
// (= OverlayHost は閉じた overlay を unmount する)。 開閉の真値は `ui.overlays.extensionOpen`
// (= 開いている id、 null で全部畳む) で、 画面共有との排他は state/ui.js が持つ。
export default function ExtensionHost() {
  const extensions = useExtensions()
  const openId = useSyncExternalStore(subscribeUi, () => getUiSnapshot().overlays.extensionOpen)
  const [mountedIds, setMountedIds] = useState([])
  const [fullId, setFullId] = useState(null)
  const t = useT()

  const open = extensions.find((ext) => ext.id === openId) || null
  // 開かれた id を mount 済みに加える (= render 中の state 調整、 開いた瞬間の 1 回だけ走る)。
  if (open && !mountedIds.includes(open.id)) {
    setMountedIds([...mountedIds, open.id])
  }
  const full = open !== null && fullId === open.id
  const mounted = extensions.filter((ext) => mountedIds.includes(ext.id))
  if (mounted.length === 0) return null

  return (
    <div
      className={`extension-band ${open ? '' : 'collapsed'} ${full ? 'fullscreen' : ''}`}
      data-testid="extension-band"
    >
      {mounted.map((ext) => (
        <iframe
          key={ext.id}
          src={ext.path}
          title={ext.title}
          className={`extension-iframe ${ext.id === openId ? '' : 'inactive'}`}
          allow="autoplay; fullscreen"
          data-testid={`extension-iframe-${ext.id}`}
        />
      ))}
      {open && (
        <button
          className="extension-ctrl-btn"
          onClick={() => setFullId(full ? null : open.id)}
          aria-label={full ? t('extensions.exit_fullscreen') : t('extensions.enter_fullscreen')}
          title={full ? t('extensions.exit_fullscreen') : t('extensions.enter_fullscreen')}
        >
          ⛶
        </button>
      )}
    </div>
  )
}
