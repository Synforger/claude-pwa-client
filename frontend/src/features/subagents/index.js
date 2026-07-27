// features/subagents 配線 entry。
//
// SubagentsModal.jsx は OverlayHost が Component spec 経由で lazy render する。 配線 entry での
// static import は chunk 分離を壊し INEFFECTIVE_DYNAMIC_IMPORT 警告の原因になるため、
// entry は registry signal のみ。

import { register as registerOverlay } from '../../registry/overlayRegistry.js'

// Component spec で OverlayHost 経由 lazy 化、 SubagentsModal が引数なしで state を自己解決する。
registerOverlay('subagents', {
  dispatch: () => null,
  Component: () => import('./SubagentsModal.jsx'),
})
