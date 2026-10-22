// features/status-bar 配線 entry。

import { register as registerStream } from '../../core/streamRegistry.js'

import './StatusBar.jsx'
import './useStatus.js'

const noopDispatch = () => null
registerStream('budget',  { dispatch: noopDispatch })
