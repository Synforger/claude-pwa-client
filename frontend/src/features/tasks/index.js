// features/tasks 配線 entry。
//
// TasksModal.jsx は AppShell.jsx で lazy(() => import(...)) されるため、 配線 entry での static import
// は chunk 分離を壊し INEFFECTIVE_DYNAMIC_IMPORT 警告の原因になる。 entry からは modal の load を外す。
// TaskNotification.jsx / ActivityBar.jsx は AppShell.jsx 側で常時 mount される (= lazy でない) 経路で
// 直接 import されるので、 entry での重複 import 不要。

import { register as registerOverlay } from '../../registry/overlayRegistry.js'
import { register as registerStream } from '../../registry/streamRegistry.js'

const noopDispatch = () => null
// W2 Phase E-2 (= 2026-06-29): Component spec で OverlayHost 経由 lazy 化。 AppShell.jsx の
// `lazy(() => import('./TasksModal.jsx'))` を撤去、 TasksModal が引数なしで自己解決する。
registerOverlay('tasks', {
  dispatch: noopDispatch,
  Component: () => import('./TasksModal.jsx'),
})
registerStream('task_notification', { dispatch: noopDispatch })
