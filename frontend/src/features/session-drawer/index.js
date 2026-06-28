// features/session-drawer 配線 entry (= 設計書 § 9-6 step 5)。

import { register as registerOverlay } from '../../registry/overlayRegistry.js'
import { register as registerStream } from '../../registry/streamRegistry.js'

import './SessionDrawer.jsx'
import './useSessions.js'
import './useSessionsOverview.js'
import './applyOverviewSnapshot.js'

const noopDispatch = () => null
registerOverlay('drawer', { dispatch: noopDispatch })

// mode / permission_mode は session-level state、 status bar とどちらが宿主にするかは
// 将来検討。 W2 では session-drawer 側で wiring signal を立てる。
registerStream('mode',            { dispatch: noopDispatch })
registerStream('permission_mode', { dispatch: noopDispatch })
