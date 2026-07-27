// features/attachments 配線 entry。

import { register as registerStream } from '../../registry/streamRegistry.js'

import './useAttachments.js'
import './AttachedImages.jsx'
import './imageStore.js'

const noopDispatch = () => null
registerStream('attachment', { dispatch: noopDispatch }, { replace: true })
