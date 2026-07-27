// features/session-drawer 配線 entry (= 設計書 § 9-6 step 5)。
//
// SessionDrawer.jsx は OverlayHost が Component spec 経由で lazy render する。 配線 entry での
// static import は chunk 分離を壊し INEFFECTIVE_DYNAMIC_IMPORT 警告の原因になるため、
// entry は registry signal のみ。

import { register as registerOverlay } from '../../registry/overlayRegistry.js'
import { register as registerStream } from '../../registry/streamRegistry.js'

const noopDispatch = () => null
// Component spec で OverlayHost 経由 lazy 化、 SessionDrawer が引数なしで自己解決する。
registerOverlay('drawer', {
  dispatch: noopDispatch,
  Component: () => import('./SessionDrawer.jsx'),
})

// mode / permission_mode は session-level state、 status bar とどちらが宿主にするかは
// 将来検討。 W2 では session-drawer 側で wiring signal を立てる。
registerStream('mode',            { dispatch: noopDispatch })
registerStream('permission_mode', { dispatch: noopDispatch })
