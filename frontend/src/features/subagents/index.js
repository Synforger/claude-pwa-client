// features/subagents 配線 entry。
//
// SubagentsModal.jsx は AppShell.jsx で lazy(() => import(...)) される。 配線 entry での static import
// は chunk 分離を壊し INEFFECTIVE_DYNAMIC_IMPORT 警告の原因になるため、 entry は registry signal のみ。

import { register as registerOverlay } from '../../registry/overlayRegistry.js'

// W2 Phase E-2 (= 2026-06-29): Component spec で OverlayHost 経由 lazy 化。 旧来 AppShell.jsx
// の `lazy(() => import('./SubagentsModal.jsx'))` を撤去、 SubagentsModal が引数なしで
// state を自己解決する。
registerOverlay('subagents', {
  dispatch: () => null,
  Component: () => import('./SubagentsModal.jsx'),
})
