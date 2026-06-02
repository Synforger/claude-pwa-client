import { useState } from 'react'
import { apiFetch } from '../utils/api.js'
import './TaskNotification.css'

// background task (= Monitor / バックグラウンド Bash 等) の完了通知を表す中央寄せの system カード。
// summary を 1 行で出し、 タップで output-file の中身を fetch して展開する (もう一度で畳む)。
// exit code が 0 以外なら error 色。 これにより harness の `<task-notification>` が
// 「自分が送ったメッセージ」 風に右寄せ表示される誤表示を解消する。
function TaskNotification({ msg }) {
  const [open, setOpen] = useState(false)
  const [content, setContent] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)

  const isError = msg.exitCode != null && msg.exitCode !== 0
  const label = msg.summary || 'background task'
  const canExpand = !!msg.outputFile

  async function toggle() {
    const next = !open
    setOpen(next)
    // 初回展開時のみ fetch (= 以降は cache 済の content を再利用)
    if (next && content == null && error == null && msg.outputFile) {
      setLoading(true)
      try {
        const res = await apiFetch(`/task-output?path=${encodeURIComponent(msg.outputFile)}`)
        if (!res.ok) {
          setError(`出力を読めませんでした (${res.status})`)
        } else {
          const data = await res.json()
          setContent(typeof data?.content === 'string' ? data.content : '')
        }
      } catch {
        setError('出力の取得に失敗しました')
      } finally {
        setLoading(false)
      }
    }
  }

  return (
    <div className="message system task-note">
      <div className={`task-note-card${isError ? ' is-error' : ''}`}>
        <button
          type="button"
          className="task-note-head"
          onClick={canExpand ? toggle : undefined}
          disabled={!canExpand}
        >
          <span className="task-note-icon">{isError ? '⚠' : '⚙'}</span>
          <span className="task-note-label">{label}</span>
          {canExpand && <span className="task-note-chevron">{open ? '▾' : '▸'}</span>}
        </button>
        {open && (
          <div className="task-note-body">
            {loading && <span className="task-note-dim">読み込み中…</span>}
            {error && <span className="task-note-dim">{error}</span>}
            {!loading && !error && (
              <pre className="task-note-output">{content || '(出力は空です)'}</pre>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

export default TaskNotification
