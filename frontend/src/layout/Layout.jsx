// 全体配置 (= drawer / chat panel / terminal pane の grid + viewport breakpoint)。
// App.jsx は薄い entry に、 配置 / routing は本 file に集約 (= 設計書 § 3-1 v2 ディレクトリツリー)。
//
// Phase E 段階: features/ がまだ未実装のため、 子要素 (= drawer / panel / pane) は Phase F で
// features/*/index.js を import + isEnabled(name) で wiring する。 現状は構造のみ定義、 features
// 配置点を JSX 上で明示。

import { useSyncExternalStore } from 'react'
import { getSnapshot as getUiSnapshot, subscribe as subscribeUi } from '../state/ui.js'
import { getSnapshot as getSessionsSnapshot, subscribe as subscribeSessions } from '../state/sessions.js'
import ChatPanel from './ChatPanel.jsx'
import TerminalPane from './TerminalPane.jsx'

export default function Layout() {
  const ui = useSyncExternalStore(subscribeUi, getUiSnapshot)
  const sessions = useSyncExternalStore(subscribeSessions, getSessionsSnapshot)

  const activeSid = sessions.activeId
  const viewMode = activeSid ? (ui.viewModes[activeSid] || 'chat') : 'chat'

  return (
    <div className="cpc-layout">
      {/* drawer は features/session-drawer/ が Phase F で register、 ここでは flag を見て条件描画 */}
      {ui.overlays.drawer && <div className="cpc-drawer-slot" data-feature="session-drawer" />}

      <main className="cpc-main">
        {activeSid && viewMode === 'chat' && <ChatPanel sid={activeSid} />}
        {activeSid && viewMode === 'terminal' && <TerminalPane sid={activeSid} />}
      </main>

      {/* overlay 系 (= modal / panel) は features 側で portal、 ここでは sentinel のみ */}
      <div className="cpc-overlay-root" data-overlay-portal />
    </div>
  )
}
