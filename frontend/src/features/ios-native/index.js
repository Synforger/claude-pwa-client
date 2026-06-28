// features/ios-native 配線 entry。

import { register as registerFeature } from '../../registry/featureRegistry.js'

import './OnScreenKeyboard.jsx'
import './useKeyboardState.js'

registerFeature('ios-native', { requires: ['terminal'], dispatch: () => null })
