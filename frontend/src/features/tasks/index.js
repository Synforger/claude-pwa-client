// features/tasks 配線 entry (= W2 真の完成、 ADR-026 + 残骸 sweep)。
//
// task kind の system message render は features/tasks 責務として本 file で register
// (= 旧 src/messageRegistry.js から本 feature に集約)。 入力欄の上の帯 (= ActivityBar) は
// ChatPanel が直に置く。 📋 のボタンが開くのはタブのメモ (= features/notes) で、 task の一覧の
// 画面は持たない。

import { register as registerStream } from '../../registry/streamRegistry.js'
import { register as registerMessage } from '../../registry/messageRegistry.js'

import TaskNotification from './TaskNotification.jsx'

const noopDispatch = () => null

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
