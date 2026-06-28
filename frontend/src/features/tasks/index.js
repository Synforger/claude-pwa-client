// features/tasks 配線 entry。

import { register as registerOverlay } from '../../registry/overlayRegistry.js'
import { register as registerStream } from '../../registry/streamRegistry.js'

import './TasksModal.jsx'
import './TaskNotification.jsx'
import './ActivityBar.jsx'

const noopDispatch = () => null
registerOverlay('tasks', { dispatch: noopDispatch })
registerStream('task_notification', { dispatch: noopDispatch })
