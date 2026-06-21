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

  // F-51: exitCode 未確定 (= まだ走っているか、 終了報告が届く前) のうちは tail が増え
  // 続けるので cache せず、 開くたび再 fetch する。 確定 (= exitCode != null) 後の content
  // は cache を再利用 (= 値が変わらないため)。 確定後でも明示的に「再読込」 を押せば
  // 強制 refetch する (= 出力ファイルが手で書き換わった場合の救済)。
  const isFinal = msg.exitCode != null

  async function loadOutput() {
    if (!msg.outputFile) return
    setLoading(true)
    setError(null)
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

  async function toggle() {
    const next = !open
    setOpen(next)
    if (!next) return
    // (a) 初回 open (= content/error がまだ無い) は必ず fetch
    // (b) 未確定 task は開くたび毎回 refetch (= tail が増えうるので cache 不可)
    if (msg.outputFile && (content == null && error == null || !isFinal)) {
      await loadOutput()
    }
  }

  // 確定後の「再読込」 ボタン用 handler (= toggle と独立)。
  const handleReload = async (e) => {
    e.stopPropagation()
    await loadOutput()
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
              <>
                <pre className="task-note-output">{content || '(出力は空です)'}</pre>
                {msg.outputFile && (
                  <button
                    type="button"
                    className="task-note-reload"
                    onClick={handleReload}
                    disabled={loading}
                    title="出力ファイルを再読み込み"
                  >
                    ↻ 再読込
                  </button>
                )}
              </>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

export default TaskNotification
