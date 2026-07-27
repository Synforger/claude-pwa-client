// features/push-notify 配線 entry。

import { register as registerPush } from '../../registry/pushRegistry.js'

import './usePushSubscription.js'
import './push.js'
import './badge.js'

const noopDispatch = () => null
registerPush('default', { dispatch: noopDispatch })
