// features/attachments 配線 entry。

import { register as registerFeature } from '../../registry/featureRegistry.js'
import { register as registerStream } from '../../registry/streamRegistry.js'

import './useAttachments.js'
import './AttachedImages.jsx'
import './imageStore.js'

const noopDispatch = () => null
registerFeature('attachments', { dispatch: noopDispatch })
registerStream('attachment', { dispatch: noopDispatch }, { replace: true })
