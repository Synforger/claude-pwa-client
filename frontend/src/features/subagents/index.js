// features/subagents 配線 entry。
//
// SubagentsModal.jsx は AppShell.jsx で lazy(() => import(...)) される。 配線 entry での static import
// は chunk 分離を壊し INEFFECTIVE_DYNAMIC_IMPORT 警告の原因になるため、 entry は registry signal のみ。

import { register as registerOverlay } from '../../registry/overlayRegistry.js'

registerOverlay('subagents', { dispatch: () => null })
