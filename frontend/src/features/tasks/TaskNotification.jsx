import { setOverlay } from '../../state/ui.js'
import { useT } from '../../i18n/t.js'
import { classifyTaskNotification, iconForTaskType } from './classifyTaskNotification.js'
import './TaskNotification.css'

// background task (= Task subagent / バックグラウンド Bash / Monitor) の完了通知を表す中央寄せ
// の system カード。 exit code が 0 以外なら error 色。 タップで開く modal は summary 由来の
// 型 (= agent / bash / monitor / unknown) で切り分ける (= 2026-07-03、 subagent 以外まで
// 「サブエージェント」 modal に流れて混同する UX 事故の解消)。
//   - agent → SubagentsModal に taskOutputPath focus (= /task-transcript 構造化 render)
//   - bash / monitor / unknown → TaskOutputModal (= /task-output raw render、 独立 modal)
function TaskNotification({ msg }) {
  const t = useT()
  const type = classifyTaskNotification(msg.summary)
  const isError = msg.exitCode != null && msg.exitCode !== 0
  const label = msg.summary || t('task_note.background_task')
  const canOpen = !!msg.outputFile

  const openDetail = () => {
    if (!msg.outputFile) return
    if (type === 'agent') {
      setOverlay('subagentsFocus', { kind: 'taskOutputPath', value: msg.outputFile })
      setOverlay('subagents', true)
    } else {
      setOverlay('taskOutputPath', msg.outputFile)
    }
  }

  const icon = isError ? '⚠' : iconForTaskType(type)

  return (
    <div className="message system task-note">
      <div className={`task-note-card${isError ? ' is-error' : ''}`}>
        <button
          type="button"
          className="task-note-head"
          onClick={canOpen ? openDetail : undefined}
          disabled={!canOpen}
          title={canOpen ? t('task_note.open_detail') : undefined}
        >
          <span className="task-note-icon">{icon}</span>
          <span className="task-note-label">{label}</span>
          {canOpen && <span className="task-note-chevron">›</span>}
        </button>
      </div>
    </div>
  )
}

export default TaskNotification
