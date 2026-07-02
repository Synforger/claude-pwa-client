import { setOverlay } from '../../state/ui.js'
import './TaskNotification.css'

// background task (= Monitor / バックグラウンド Bash / Task subagent) の完了通知を表す中央寄せ
// の system カード。 exit code が 0 以外なら error 色。 タップで SubagentsModal を outputFile
// 起点 (= taskOutputPath focus) で開く。 中身の transcript / raw 表示はモーダル側に集約したので
// カード本文はインライン展開しない (= 会話流の視覚ノイズ削減、 2026-07-02)。
function TaskNotification({ msg }) {
  const isError = msg.exitCode != null && msg.exitCode !== 0
  const label = msg.summary || 'background task'
  const canOpen = !!msg.outputFile

  const openInSubagents = () => {
    if (!msg.outputFile) return
    setOverlay('subagentsFocus', { kind: 'taskOutputPath', value: msg.outputFile })
    setOverlay('subagents', true)
  }

  return (
    <div className="message system task-note">
      <div className={`task-note-card${isError ? ' is-error' : ''}`}>
        <button
          type="button"
          className="task-note-head"
          onClick={canOpen ? openInSubagents : undefined}
          disabled={!canOpen}
          title={canOpen ? '詳細を開く' : undefined}
        >
          <span className="task-note-icon">{isError ? '⚠' : '⚙'}</span>
          <span className="task-note-label">{label}</span>
          {canOpen && <span className="task-note-chevron">›</span>}
        </button>
      </div>
    </div>
  )
}

export default TaskNotification
