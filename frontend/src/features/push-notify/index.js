// features/push-notify 配線 entry。

import { register as registerFeature } from '../../registry/featureRegistry.js'
import { register as registerPush } from '../../registry/pushRegistry.js'

import './usePushSubscription.js'
import './push.js'
import './badge.js'

const noopDispatch = () => null
registerFeature('push-notify', { dispatch: noopDispatch })
registerPush('default', { dispatch: noopDispatch })
