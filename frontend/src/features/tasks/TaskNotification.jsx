import { useState } from 'react'
import { setOverlay } from '../../state/ui.js'
import { useT } from '../../i18n/t.js'
import { classifyTaskNotification, iconForTaskType } from './classifyTaskNotification.js'
import TaskOutputBody from './TaskOutputBody.jsx'
import './TaskNotification.css'

// background task (= Task subagent / バックグラウンド Bash / Monitor) の完了通知を表す中央寄せ
// の system カード。 exit code が 0 以外なら error 色。 タップ挙動は summary 由来の型で切替:
//   - agent → SubagentsModal に taskOutputPath focus (= /task-transcript 構造化 render、 modal)
//   - bash / monitor / unknown → カード直下に inline 展開 (= /task-output raw、 2026-07-05。
//     旧 TaskOutputModal は退役 — 会話の流れから modal に飛ばされる断絶をなくし、 tool-block
//     の ▸/▾ 開閉と同じ所作に揃えた)
function TaskNotification({ msg }) {
  const t = useT()
  const [open, setOpen] = useState(false)
  const type = classifyTaskNotification(msg.summary)
  const isError = msg.exitCode != null && msg.exitCode !== 0
  const label = msg.summary || t('task_note.background_task')
  const canOpen = !!msg.outputFile
  const isInline = type !== 'agent'

  const handleTap = () => {
    if (!msg.outputFile) return
    if (type === 'agent') {
      setOverlay('subagentsFocus', { kind: 'taskOutputPath', value: msg.outputFile })
      setOverlay('subagents', true)
    } else {
      setOpen(v => !v)
    }
  }

  const icon = isError ? '⚠' : iconForTaskType(type)
  const chevron = isInline ? (open ? '▾' : '▸') : '›'

  return (
    <div className="message system task-note">
      <div className={`task-note-card${isError ? ' is-error' : ''}`}>
        <button
          type="button"
          className="task-note-head"
          onClick={canOpen ? handleTap : undefined}
          disabled={!canOpen}
          title={canOpen ? t('task_note.open_detail') : undefined}
          aria-expanded={isInline ? open : undefined}
        >
          <span className="task-note-icon">{icon}</span>
          <span className="task-note-label">{label}</span>
          {canOpen && <span className="task-note-chevron">{chevron}</span>}
        </button>
        {isInline && open && canOpen && (
          <div className="task-note-body" data-testid="task-note-body">
            <TaskOutputBody path={msg.outputFile} />
          </div>
        )}
      </div>
    </div>
  )
}

export default TaskNotification
