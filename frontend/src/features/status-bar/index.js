// features/status-bar 配線 entry。

import { register as registerStream } from '../../registry/streamRegistry.js'

import './StatusBar.jsx'
import './useStatus.js'

const noopDispatch = () => null
registerStream('budget',  { dispatch: noopDispatch })
registerStream('pr_link', { dispatch: noopDispatch })
