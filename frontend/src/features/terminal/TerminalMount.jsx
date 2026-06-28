// W2 Phase F-2 (= 2026-06-29): terminal LRU mount を AppShell から features/terminal に物理移送。
// viewMode='terminal' を経験した sid を最大 N=3 で cap、 active sid だけ visible=true で render し、
// それ以外は hidden buffer 経路 (= Terminal.jsx の F-11) に WS の出力を積む。
//
// 旧 AppShell.jsx の以下を**ロジック改変ゼロ**で移送:
//   - `const [termMountedSids, setTermMountedSids] = useState([])`
//   - F-11 LRU 更新 useEffect (= activeSid / activeViewMode 変化で 1 件追加 + N=3 cap)
//   - session 削除で消えた sid を mount list から掃除する useEffect
//   - termMountedSids.map で <Terminal sessionId={sid} visible={isVisible} /> を absolute 子要素として
//     展開する render block
//
// termMountedSids は module-level の独自 store にする (= 旧 useState からの形式置換)。 理由:
//   - TerminalMount が複数 instance 化された場合の二重 instantiate / state 分裂を防ぐ (= 防御的、
//     現状 AppShell が単一配置だが Layout.jsx 等の経路も理論上ありうる)
//   - LRU は process 単位で 1 経路あれば十分 (= 旧 AppShell の useState が「単一 AppShell mount」
//     前提だったのと同じ哲学を、 物理場所を変えても保つ)
//
// 表示 gate (= viewMode != 'terminal' で全部 hidden) は TerminalPane.jsx 側で `display: none` を
// 当てる構造、 本 component は LRU と Terminal 子要素 + visible prop の同期だけを担う。
import { useSyncExternalStore, useEffect, useMemo } from 'react'
import Terminal from './Terminal.jsx'
import { subscribe as subscribeUi, getSnapshot as getUiSnapshot } from '../../state/ui.js'
import {
  subscribe as subscribeSessions,
  getSnapshot as getSessionsSnapshot,
} from '../../state/sessions.js'

// 旧 AppShell の TERM_MOUNT_LRU 定数 (= F-11) を物理移送。 N=3 は「直近 3 sid だけ WS と xterm を
// 生かす」 = 多 sid 開きっぱでも memory / CPU を上限 cap する設計指針 (= 設計判断は据置)。
const TERM_MOUNT_LRU = 3

// module-level 単一 store (= 旧 useState の 1 instance 化前提を物理場所変えで保つ防御)。
// useSyncExternalStore + 独自 subscribe で React 側に変更通知、 setLru で同値 ref は skip する。
let termMountedSids = []
const lruListeners = new Set()
function getLruSnapshot() { return termMountedSids }
function subscribeLru(listener) {
  lruListeners.add(listener)
  return () => lruListeners.delete(listener)
}
function setLru(next) {
  if (next === termMountedSids) return
  termMountedSids = next
  for (const fn of Array.from(lruListeners)) {
    try { fn(next) } catch (e) {
      console.error('[terminal-mount] listener threw', e)
    }
  }
}

export default function TerminalMount({ sid }) {
  // ui.viewModes は active sid の表示モード判定 (= 旧 AppShell と同じ派生値ルート)。 sessions は
  // session 削除 cleanup の入力 (= sids の live 集合)。 LRU store は本 component 内 mount 配列。
  const ui = useSyncExternalStore(subscribeUi, getUiSnapshot)
  const sessionsSnap = useSyncExternalStore(subscribeSessions, getSessionsSnapshot)
  const mounted = useSyncExternalStore(subscribeLru, getLruSnapshot)

  const activeSid = sid || null
  const activeViewMode = activeSid ? (ui.viewModes[activeSid] || 'chat') : 'chat'

  // F-11 (= 2026-06-21): 旧 AppShell の LRU 更新 useEffect を物理移送、 ロジック改変ゼロ。
  // 「viewMode='terminal' に切替えた sid」 を先頭に置く LRU、 N=3 超過は最古を捨てる。
  useEffect(() => {
    if (!activeSid) return
    if (activeViewMode !== 'terminal') return
    const prev = termMountedSids
    if (prev[0] === activeSid) return
    const next = [activeSid, ...prev.filter(s => s !== activeSid)]
    setLru(next.length > TERM_MOUNT_LRU ? next.slice(0, TERM_MOUNT_LRU) : next)
  }, [activeSid, activeViewMode])

  // session 削除で消えた sid を mount list からも掃除 (= 旧 AppShell から物理移送)。
  const sessionsList = sessionsSnap.sessions
  const sids = useMemo(() => sessionsList.map(s => s.id), [sessionsList])
  useEffect(() => {
    const live = new Set(sids)
    const prev = termMountedSids
    const filtered = prev.filter(s => live.has(s))
    if (filtered.length !== prev.length) setLru(filtered)
  }, [sids])

  return mounted.map(s => {
    const isVisible = activeViewMode === 'terminal' && s === activeSid
    return (
      <div
        key={s}
        style={{
          display: isVisible ? 'block' : 'none',
          position: 'absolute',
          inset: 0,
        }}
      >
        <Terminal sessionId={s} visible={isVisible} />
      </div>
    )
  })
}
