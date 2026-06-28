// features/terminal 配線 entry。

import { register as registerFeature } from '../../registry/featureRegistry.js'

import './Terminal.jsx'
import './useTerminal.js'

registerFeature('terminal', { dispatch: () => null })
