// ADR-012 DebugPanel: 右下に張り付く debug overlay。 5 sub-tab + log capture install。
//
// 二重 gate (= ADR-012 + 99-references § 12-3):
//   build-time 一次 gate: import.meta.env.DEV (= prod build で完全消失)
//   runtime 二次 gate (= prod 残す場合): ?debug=1 AND localStorage `cpc_debug_token`
//
// production build では SHOW=false の path に倒れて何も render しない (= bundle に残るが
// inert)。 dev では即 visible、 prod では token + ?debug=1 で開発者の手元 PC のみ visible。

import { useEffect, useState } from 'react'
import StateInspector from './StateInspector.jsx'
import TransportInspector from './TransportInspector.jsx'
import EventTimeline from './EventTimeline.jsx'
import ReplayControl from './ReplayControl.jsx'
import PerfHud from './PerfHud.jsx'
import { captureConsole, uninstallConsole } from './log.js'

function shouldShow() {
  // build-time 一次 gate (= prod では false 確定、 vite が tree-shake する)
  if (import.meta.env && import.meta.env.DEV) return true
  // runtime 二次 gate (= prod 残し時、 開発者手元で手動 enable)
  try {
    const q = new URLSearchParams(window.location.search)
    if (q.get('debug') !== '1') return false
    return Boolean(window.localStorage.getItem('cpc_debug_token'))
  } catch {
    return false
  }
}

const TABS = [
  { id: 'state', label: 'State', Component: StateInspector },
  { id: 'transport', label: 'Transport', Component: TransportInspector },
  { id: 'events', label: 'Events', Component: EventTimeline },
  { id: 'replay', label: 'Replay', Component: ReplayControl },
  { id: 'perf', label: 'Perf', Component: PerfHud },
]

export default function DebugPanel() {
  const [show] = useState(() => shouldShow())
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState('state')

  useEffect(() => {
    if (!show) return
    captureConsole()
    return () => uninstallConsole()
  }, [show])

  if (!show) return null

  const Tab = TABS.find(t => t.id === active)?.Component ?? StateInspector

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        style={{
          position: 'fixed', right: 12, bottom: 12, zIndex: 99999,
          padding: '6px 10px', borderRadius: 6, border: '1px solid #888', background: '#222', color: '#fff',
          fontFamily: 'monospace', fontSize: 12, cursor: 'pointer',
        }}
        aria-label="Open debug panel"
      >
        debug
      </button>
    )
  }

  return (
    <aside
      style={{
        position: 'fixed', right: 12, bottom: 12, zIndex: 99999,
        width: 480, maxWidth: 'calc(100vw - 24px)', height: 480, maxHeight: 'calc(100vh - 24px)',
        background: '#fff', color: '#222', border: '1px solid #555', borderRadius: 8,
        boxShadow: '0 4px 16px rgba(0,0,0,0.3)', display: 'flex', flexDirection: 'column',
      }}
    >
      <header style={{ display: 'flex', alignItems: 'center', padding: 6, borderBottom: '1px solid #ddd' }}>
        <strong style={{ flex: '0 0 auto', marginRight: 8, fontFamily: 'monospace' }}>debug</strong>
        <nav style={{ flex: '1 1 auto', display: 'flex', gap: 4 }}>
          {TABS.map(t => (
            <button
              key={t.id}
              onClick={() => setActive(t.id)}
              style={{
                padding: '4px 8px', fontSize: 12, cursor: 'pointer',
                background: t.id === active ? '#222' : '#eee', color: t.id === active ? '#fff' : '#222',
                border: '1px solid #ccc', borderRadius: 4,
              }}
            >
              {t.label}
            </button>
          ))}
        </nav>
        <button onClick={() => setOpen(false)} style={{ marginLeft: 'auto' }}>×</button>
      </header>
      <div style={{ flex: '1 1 auto', overflow: 'auto' }}>
        <Tab />
      </div>
    </aside>
  )
}
