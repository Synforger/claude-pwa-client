import { useRef, useState, useSyncExternalStore } from 'react'
import { subscribe as subscribeUi, getSnapshot as getUiSnapshot, setOverlay } from '../../state/ui.js'
import { useT } from '../../i18n/t.js'
import { useExtensions } from './useExtensions.js'
import { loadBandPct, pctAfterDrag, saveBandPct } from './bandHeight.js'
import './ExtensionHost.css'

// 拡張の枠 (= チャットの上の帯)。 Layout が Topbar の直後に常時 mount する。
//
// 一度開いた拡張の iframe は閉じても破棄せず畳むだけにする (= 閉じた瞬間に拡張の音や接続が
// 切れないように)。 破棄されるのは PWA の再読込の時だけ。 そのため overlayRegistry には載せない
// (= OverlayHost は閉じた overlay を unmount する)。 開閉の真値は `ui.overlays.extensionOpen`
// (= 開いている id、 null で全部畳む) で、 画面共有との排他は state/ui.js が持つ。
//
// 帯の高さは下端の取っ手をドラッグして変え、 端末ごとに保存する (= 範囲と既定値は bandHeight.js)。
// ドラッグ中は取っ手が pointer を capture し、 iframe に指を取られない。
//
// 宣言が `view: 'page'` の拡張は、 帯ではなく頁として開く (= 入力欄の上の残り全部を使う。 メッセージの
// 一覧と端末は、 開いている間その場所を譲る)。 頁には決める高さが無いので、 取っ手も全画面も出さない。
export default function ExtensionHost() {
  const extensions = useExtensions()
  const openId = useSyncExternalStore(subscribeUi, () => getUiSnapshot().overlays.extensionOpen)
  const [mountedIds, setMountedIds] = useState([])
  const [fullId, setFullId] = useState(null)
  const [bandPct, setBandPct] = useState(loadBandPct)
  const [resizing, setResizing] = useState(false)
  const dragRef = useRef(null)
  const t = useT()

  const onResizeStart = (e) => {
    e.currentTarget.setPointerCapture(e.pointerId)
    dragRef.current = { startY: e.clientY, startPct: bandPct }
    setResizing(true)
  }
  const onResizeMove = (e) => {
    const drag = dragRef.current
    if (!drag) return
    setBandPct(pctAfterDrag(drag.startPct, e.clientY - drag.startY, window.innerHeight))
  }
  const onResizeEnd = () => {
    if (!dragRef.current) return
    dragRef.current = null
    setResizing(false)
    saveBandPct(bandPct)
  }

  const open = extensions.find((ext) => ext.id === openId) || null
  // 開かれた id を mount 済みに加える (= render 中の state 調整、 開いた瞬間の 1 回だけ走る)。
  if (open && !mountedIds.includes(open.id)) {
    setMountedIds([...mountedIds, open.id])
  }
  const page = open !== null && open.view === 'page'
  const full = open !== null && !page && fullId === open.id
  const mounted = extensions.filter((ext) => mountedIds.includes(ext.id))
  if (mounted.length === 0) return null

  return (
    <div
      className={`extension-band ${open ? '' : 'collapsed'} ${page ? 'page' : ''} ${full ? 'fullscreen' : ''} ${resizing ? 'resizing' : ''}`}
      style={open && !full && !page ? { height: `${bandPct}dvh` } : undefined}
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
      {open && !page && (
        <button
          className="extension-ctrl-btn extension-ctrl-full"
          onClick={() => setFullId(full ? null : open.id)}
          aria-label={full ? t('extensions.exit_fullscreen') : t('extensions.enter_fullscreen')}
          title={full ? t('extensions.exit_fullscreen') : t('extensions.enter_fullscreen')}
        >
          ⛶
        </button>
      )}
      {/* ✕ = 帯を畳む (= 🧩 の一覧でもう一度選ぶのと同じ、 iframe は残るので音は止まらない)。
          全画面の時は全画面も解く。 */}
      {open && (
        <button
          className="extension-ctrl-btn extension-ctrl-close"
          onClick={() => { setFullId(null); setOverlay('extensionOpen', null) }}
          aria-label={t('extensions.close')}
          title={t('extensions.close')}
          data-testid="extension-close"
        >
          ✕
        </button>
      )}
      {open && !full && !page && (
        <div
          className="extension-resize"
          onPointerDown={onResizeStart}
          onPointerMove={onResizeMove}
          onPointerUp={onResizeEnd}
          onPointerCancel={onResizeEnd}
          role="separator"
          aria-orientation="horizontal"
          aria-label={t('extensions.resize')}
          data-testid="extension-resize"
        >
          <span className="extension-resize-grip" />
        </div>
      )}
    </div>
  )
}
