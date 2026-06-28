// features/screenshare 配線 entry。

import { register as registerFeature } from '../../registry/featureRegistry.js'

import './MoonlightFrame.jsx'

registerFeature('screenshare', { dispatch: () => null })
