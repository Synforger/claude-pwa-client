// features/session-drawer 配線 entry (= 設計書 § 9-6 step 5)。
//
// SessionDrawer.jsx は AppShell.jsx で lazy(() => import(...)) される。 配線 entry での static import
// は chunk 分離を壊し INEFFECTIVE_DYNAMIC_IMPORT 警告の原因になるため、 entry は registry signal のみ。
// useSessions / useSessionsOverview / applyOverviewSnapshot は AppShell.jsx から直接 import される
// 非 lazy module で、 ここでの touch import は重複 (= 直接 import 側で module load が起きる)。

import { register as registerOverlay } from '../../registry/overlayRegistry.js'
import { register as registerStream } from '../../registry/streamRegistry.js'

const noopDispatch = () => null
registerOverlay('drawer', { dispatch: noopDispatch })

// mode / permission_mode は session-level state、 status bar とどちらが宿主にするかは
// 将来検討。 W2 では session-drawer 側で wiring signal を立てる。
registerStream('mode',            { dispatch: noopDispatch })
registerStream('permission_mode', { dispatch: noopDispatch })
