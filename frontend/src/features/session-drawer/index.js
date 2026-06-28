// features/session-drawer 配線 entry (= 設計書 § 9-6 step 5)。
// v2 では overlayRegistry / streamRegistry に self-register する。
// W2 Phase F-session-drawer 段階: 物理移送 + import path 修正のみ。 v2 state/registry 経由への
// 深化は後続 commit で。

import './SessionDrawer.jsx'
import './useSessions.js'
import './useSessionsOverview.js'
import './applyOverviewSnapshot.js'

// TODO: 後続 commit で
//   import { register as registerOverlay } from '../../registry/overlayRegistry.js'
//   registerOverlay('drawer', { dispatch: ({ type }) => { ... } })
//   import { register as registerStream } from '../../registry/streamRegistry.js'
//   registerStream('mode', { dispatch: handleModeChange })
//   registerStream('permission_mode', { dispatch: handlePermissionModeChange })
