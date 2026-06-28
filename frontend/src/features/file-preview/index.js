// features/file-preview 配線 entry。

import { register as registerOverlay } from '../../registry/overlayRegistry.js'

import './FilePreviewModal.jsx'

registerOverlay('previewPath', { dispatch: () => null })
