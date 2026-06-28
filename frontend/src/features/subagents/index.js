// features/subagents 配線 entry。

import { register as registerOverlay } from '../../registry/overlayRegistry.js'

import './SubagentsModal.jsx'

registerOverlay('subagents', { dispatch: () => null })
