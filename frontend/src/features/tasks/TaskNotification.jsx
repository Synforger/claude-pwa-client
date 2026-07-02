import { useState } from 'react'
import { apiFetch } from '../../utils/api.js'
import TranscriptEvent from '../subagents/TranscriptEvent.jsx'
import './TaskNotification.css'

// background task (= Monitor / バックグラウンド Bash 等) の完了通知を表す中央寄せの system カード。
// summary を 1 行で出し、 タップで output-file の中身を fetch して展開する (もう一度で畳む)。
// exit code が 0 以外なら error 色。 これにより harness の `<task-notification>` が
// 「自分が送ったメッセージ」 風に右寄せ表示される誤表示を解消する。
//
// 2 段構え取得: sid + taskId があれば `/sessions/{sid}/subagents/agent-{taskId}/transcript`
// を先に試し、 hit すれば subagent JSONL の構造化 event として描画する。 miss (= Monitor / Bash
// 系の task で subagent 経路が無い場合、 または旧 claude harness で symlink 化されてない場合) は
// `/task-output` に fallback して raw text を pre で出す。 これで PWA 展開時に「Agent 出力を
// 綺麗に読める」 + 「Monitor 出力も引き続き読める」 の両立になる (= 2026-07-02 顛末、 Claude Code
// が `<task-notification>` output-file を subagent jsonl symlink に変えた事への追随)。
function TaskNotification({ msg }) {
  const [open, setOpen] = useState(false)
  const [events, setEvents] = useState(null)  // 構造化描画用 (= subagent transcript hit 時)
  const [content, setContent] = useState(null)  // raw 描画用 (= /task-output fallback 時)
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
    // 1. subagent transcript を先に試す (= sid + taskId が来てて、 かつ Task/Agent 由来のもの)
    if (msg.sid && msg.taskId) {
      try {
        const res = await apiFetch(
          `/sessions/${encodeURIComponent(msg.sid)}/subagents/${encodeURIComponent(`agent-${msg.taskId}`)}/transcript`,
        )
        if (res.ok) {
          const data = await res.json()
          const evs = Array.isArray(data?.events) ? data.events : []
          if (evs.length > 0) {
            setEvents(evs)
            setContent(null)
            setLoading(false)
            return
          }
        }
      } catch {
        // fall through to raw output
      }
    }
    // 2. fallback: raw output ファイルを読む (= Monitor / バックグラウンド Bash 等)
    try {
      const res = await apiFetch(`/task-output?path=${encodeURIComponent(msg.outputFile)}`)
      if (!res.ok) {
        setError(`出力を読めませんでした (${res.status})`)
      } else {
        const data = await res.json()
        setContent(typeof data?.content === 'string' ? data.content : '')
        setEvents(null)
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
    // (a) 初回 open (= content/events/error がまだ無い) は必ず fetch
    // (b) 未確定 task は開くたび毎回 refetch (= tail が増えうるので cache 不可)
    const hasCache = events != null || content != null || error != null
    if (msg.outputFile && (!hasCache || !isFinal)) {
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
            {!loading && !error && events && (
              <div className="task-note-transcript">
                {events.map((ev, i) => <TranscriptEvent key={i} event={ev} />)}
                {msg.outputFile && (
                  <button
                    type="button"
                    className="task-note-reload"
                    onClick={handleReload}
                    disabled={loading}
                    title="出力を再読み込み"
                  >
                    ↻ 再読込
                  </button>
                )}
              </div>
            )}
            {!loading && !error && !events && (
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
