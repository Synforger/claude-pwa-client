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

// TaskOutputModal = Bash / Monitor 由来 TaskNotification 用の raw 出力 modal (2026-07-03)。
// truthy overlay key は `taskOutputPath` (= string path、 null で閉じる semantics)。
registerOverlay('taskOutputPath', {
  dispatch: noopDispatch,
  Component: () => import('./TaskOutputModal.jsx'),
})

// task_notification SSE event → wiring signal
registerStream('task_notification', { dispatch: noopDispatch })

// background task (= Monitor / バックグラウンド Bash) の完了通知。 中央寄せ system カード。
// 展開時の transcript / raw 取得は TaskNotification 内で outputFile を起点に行う (= /task-transcript
// を先に叩き、 subagent jsonl 実体なら構造化描画、 それ以外は /task-output raw に fallback)。
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
