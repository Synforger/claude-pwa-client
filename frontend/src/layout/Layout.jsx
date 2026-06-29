// 全体配置 owner (= W2 Phase F-6、 2026-06-29)。 旧 layout/AppShell.jsx を完全削除し、
// 配置責務を本 file に集約 (= 完了判定 1)。 副作用は features/app-effects/AppEffects.jsx、
// 各責務 (= chat / terminal / topbar / overlay / storage warn) は各 feature wrapper が所有する。
// features/*/index.js は side-effect import で全部 load (= ADR-010 self-register、 § 9-6 step 5)、
// StorageWarning.css は intra-layer import で本 file が単一所有 (= features 側からは触らない)。
import { useSyncExternalStore } from 'react'
import { subscribe as subscribeSessions, getSnapshot as getSessionsSnapshot } from '../state/sessions.js'
import '../features/chat/index.js'
import '../features/session-drawer/index.js'
import '../features/status-bar/index.js'
import '../features/file-preview/index.js'
import '../features/file-tree/index.js'
import '../features/ask-user-question/index.js'
import '../features/plan-approval/index.js'
import '../features/screenshare/index.js'
import '../features/subagents/index.js'
import '../features/tasks/index.js'
import '../features/push-notify/index.js'
import '../features/attachments/index.js'
import '../features/ios-native/index.js'
import '../features/terminal/index.js'
import '../features/fork/index.js'
import '../features/topbar/index.js'
import '../features/dialogs/index.js'
import '../features/app-effects/index.js'
import ChatPanel from './ChatPanel.jsx'
import TerminalPane from './TerminalPane.jsx'
import OverlayHost from './OverlayHost.jsx'
import Topbar from '../features/topbar/Topbar.jsx'
import StatusBar from '../features/status-bar/StatusBar.jsx'
import StorageWarningHost from '../features/status-bar/StorageWarningHost.jsx'
import AppEffects from '../features/app-effects/AppEffects.jsx'
import '../App.css'

export default function Layout() {
  // ChatPanel / TerminalPane は always-mount + 内部 display:none gate (= Phase F-1, F-2 確定方針、
  // viewMode 判定は各 component が自前 subscribe で解決)、 sid だけ 1 経路で渡す (= chat 状態 +
  // xterm.js lifecycle 保持)。
  const sessions = useSyncExternalStore(subscribeSessions, getSessionsSnapshot)
  const activeSid = sessions.activeId
  return (
    <div className="app">
      {/* DOM 順序は旧 AppShell.jsx と一致 (= UI 不変保証 § 9-3): StatusBar が最上位、
          続いて StorageWarningHost、 Topbar、 ... 。 Phase J-7 で復元、 StatusBar 自身が
          props 自己解決して Layout から直接配置できる単体 component 化。 */}
      <StatusBar />
      <StorageWarningHost />
      <Topbar />
      <TerminalPane sid={activeSid} />
      <ChatPanel sid={activeSid} />
      <OverlayHost />
      <AppEffects />
    </div>
  )
}
