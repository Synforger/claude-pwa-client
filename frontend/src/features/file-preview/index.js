// features/file-preview 配線 entry。
//
// FilePreviewModal.jsx は AppShell.jsx で lazy(() => import(...)) される。 配線 entry で static import
// すると vite が dynamic import を相殺し INEFFECTIVE_DYNAMIC_IMPORT 警告を出して chunk 分離が壊れる
// ため、 entry は registry signal のみ。

import { register as registerOverlay } from '../../registry/overlayRegistry.js'

registerOverlay('previewPath', { dispatch: () => null })
