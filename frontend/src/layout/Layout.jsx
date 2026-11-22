// 全体配置 owner (= W2 Phase F-6、 2026-06-29)。 旧 layout/AppShell.jsx を完全削除し、
// 配置責務を本 file に集約 (= 完了判定 1)。 副作用は features/app-effects/AppEffects.jsx、
// 各責務 (= chat / terminal / topbar / overlay / storage warn) は各 feature wrapper が所有する。
// features/*/index.js は side-effect import で全部 load (= ADR-010 self-register、 § 9-6 step 5)、
// StorageWarning.css は intra-layer import で本 file が単一所有 (= features 側からは触らない)。
import { useRef, useSyncExternalStore } from 'react'
import { subscribe as subscribeSessions, getSnapshot as getSessionsSnapshot } from '../state/sessions.js'
import { subscribe as subscribeUi, getSnapshot as getUiSnapshot } from '../state/ui.js'
import '../features/chat/index.js'
import '../features/session-drawer/index.js'
import '../features/status-bar/index.js'
import '../features/file-preview/index.js'
import '../features/file-tree/index.js'
import '../features/ask-user-question/index.js'
import '../features/plan-approval/index.js'
import '../features/permission-window/index.js'
import '../features/screenshare/index.js'
import '../features/tasks/index.js'
import '../features/notes/index.js'
import '../features/tickets/index.js'
import '../features/settings/index.js'
import '../features/push-notify/index.js'
import '../features/attachments/index.js'
import '../features/ios-native/index.js'
import '../features/terminal/index.js'
import '../features/fork/index.js'
import '../features/topbar/index.js'
import '../features/voice/index.js'
import '../features/dialogs/index.js'
import '../features/app-effects/index.js'
import ChatPanel from './ChatPanel.jsx'
import TerminalPane from './TerminalPane.jsx'
import OverlayHost from './OverlayHost.jsx'
import Topbar from '../features/topbar/Topbar.jsx'
import OperatorReplyDock from '../features/operator-reply/OperatorReplyDock.jsx'
import ExtensionHost from '../features/extensions/ExtensionHost.jsx'
import StatusBar from '../features/status-bar/StatusBar.jsx'
import StorageWarningHost from '../features/status-bar/StorageWarningHost.jsx'
import AppEffects from '../features/app-effects/AppEffects.jsx'
import { useDockedDrawer } from '../features/session-drawer/useDockedDrawer.js'
import { useAppBarHeight } from './useAppBarHeight.js'
import './App.css'

// Whether the tab list is open. Only this boolean is subscribed, not the whole ui store, so a change such as the keyboard's does not redraw everything.
const getDrawerOpen = () => !!getUiSnapshot().overlays.drawer

export default function Layout() {
  // ChatPanel / TerminalPane は always-mount + 内部 display:none gate (= Phase F-1, F-2 確定方針、
  // viewMode 判定は各 component が自前 subscribe で解決)、 sid だけ 1 経路で渡す (= chat 状態 +
  // xterm.js lifecycle 保持)。
  const sessions = useSyncExternalStore(subscribeSessions, getSessionsSnapshot)
  const activeSid = sessions.activeId
  // While the tab list is open on a wide screen, push everything under the bar right by its width (the bar stays full width)
  const docked = useDockedDrawer()
  const drawerOpen = useSyncExternalStore(subscribeUi, getDrawerOpen)
  const drawerDocked = docked && drawerOpen
  const appRef = useRef(null)
  const barRef = useRef(null)
  useAppBarHeight(appRef, barRef)
  return (
    <div className={`app${drawerDocked ? ' drawer-docked' : ''}`} ref={appRef}>
      {/* Wraps the bar: its height is measured and handed to the docked list as its top. StatusBar stays the topmost part. */}
      <div className="app-bar" ref={barRef}>
        <StatusBar />
      </div>
      {/* Everything under the bar; only this moves right while the list is docked. Parts that cover the whole screen
          (OverlayHost) and the effects stay outside. */}
      <div className="app-main">
        <StorageWarningHost />
        <Topbar />
        {/* 帯のすぐ下、 画面の右端の引き出し (= 最後の答え)。 置き場は高さ 0 で、 チャットの場所を取らない */}
        <div className="operator-reply-anchor">
          <OperatorReplyDock />
        </div>
        <ExtensionHost />
        <TerminalPane sid={activeSid} />
        <ChatPanel sid={activeSid} />
      </div>
      <OverlayHost />
      <AppEffects />
    </div>
  )
}
