// features/tasks 配線 entry (= W2 真の完成、 ADR-026 + 残骸 sweep)。
//
// TasksModal は OverlayHost 経由 lazy 化 (= Phase E-2、 2026-06-29)。
// task kind の system message render は features/tasks 責務として本 file で register
// (= 旧 src/messageRegistry.js から本 feature に集約)。

import { register as registerOverlay } from '../../registry/overlayRegistry.js'
import { register as registerStream } from '../../registry/streamRegistry.js'
import { register as registerMessage } from '../../registry/messageRegistry.js'

import TaskNotification from './TaskNotification.jsx'

const noopDispatch = () => null

// TasksModal の OverlayHost 経由 lazy 配線 (= Component spec)
registerOverlay('tasks', {
  dispatch: noopDispatch,
  Component: () => import('./TasksModal.jsx'),
})

// task_notification SSE event → wiring signal
registerStream('task_notification', { dispatch: noopDispatch })

// background task (= Monitor / バックグラウンド Bash) の完了通知。 中央寄せ system カード。
registerMessage('task', {
  dispatch: noopDispatch,
  fromEvent: (event) => ({
    summary: event.summary || null,
    status: event.status || null,
    outputFile: event.outputFile || null,
    exitCode: typeof event.exitCode === 'number' ? event.exitCode : null,
  }),
  Render: TaskNotification,
})
