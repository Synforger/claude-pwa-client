import { useState } from 'react'
import { useT } from '../../i18n/t.js'
import { classifyTaskNotification, iconForTaskType } from './classifyTaskNotification.js'
import TaskOutputBody from './TaskOutputBody.jsx'
import './TaskNotification.css'

// background task (= Task subagent / バックグラウンド Bash / Monitor) の完了通知を表す中央寄せ
// の system カード。 exit code が 0 以外なら error 色。 タップすると型を問わずカード直下に inline 展開する
// (= /task-output raw。 会話の流れから modal に飛ばされる断絶をなくし、 tool-block の ▸/▾ 開閉と同じ所作に揃えた)。
function TaskNotification({ msg }) {
  const t = useT()
  const [open, setOpen] = useState(false)
  const type = classifyTaskNotification(msg.summary)
  const isError = msg.exitCode != null && msg.exitCode !== 0
  const label = msg.summary || t('task_note.background_task')
  const canOpen = !!msg.outputFile
  const handleTap = () => {
    if (!msg.outputFile) return
    setOpen(v => !v)
  }

  const icon = isError ? '⚠' : iconForTaskType(type)
  const chevron = open ? '▾' : '▸'

  return (
    <div className="message system task-note">
      <div className={`task-note-card${isError ? ' is-error' : ''}`}>
        <button
          type="button"
          className="task-note-head"
          onClick={canOpen ? handleTap : undefined}
          disabled={!canOpen}
          title={canOpen ? t('task_note.open_detail') : undefined}
          aria-expanded={open}
        >
          <span className="task-note-icon">{icon}</span>
          <span className="task-note-label">{label}</span>
          {canOpen && <span className="task-note-chevron">{chevron}</span>}
        </button>
        {open && canOpen && (
          <div className="task-note-body" data-testid="task-note-body">
            <TaskOutputBody path={msg.outputFile} />
          </div>
        )}
      </div>
    </div>
  )
}

export default TaskNotification
