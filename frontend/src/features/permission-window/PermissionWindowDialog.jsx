import { useEffect, useMemo, useState } from 'react'
import { useT } from '../../i18n/t.js'
import { answerWindow } from './answerWindow.js'
import { windowView } from './windowView.js'
import WindowInput from './WindowInput.jsx'
import './PermissionWindowDialog.css'

// Claude Code's permission window, lifted onto the chat screen: the tool and its input in full (the window itself may
// fold a long body), and "Allow" / "Deny". Opened from the topbar button, which shows only while
// `agent_status.pending_permission` exists; closed by the backdrop, ×, or any answer that went through or found the
// window gone.
//
// props:
//   sid: the tab's id
//   pending: agent_status.pending_permission ({number, tool_name, input, record_input, answerable, index, count, ...});
//     a window that is not `answerable` is shown, and answered in the terminal
//   onClose(): close the dialog (backdrop / × / after an answer)

export default function PermissionWindowDialog({ sid, pending, onClose }) {
  const t = useT()
  const [sending, setSending] = useState(null)
  const [failed, setFailed] = useState(false)
  const [mismatched, setMismatched] = useState(false)
  const view = useMemo(() => (pending ? windowView(pending) : null), [pending])
  const number = pending?.number

  // A newer window under the same dialog starts clean
  useEffect(() => {
    setSending(null)
    setFailed(false)
    setMismatched(false)
  }, [number])

  if (!pending || !view) return null

  const inTerminal = pending.answerable !== true || mismatched

  const handle = async (answer) => {
    if (sending || inTerminal) return
    setSending(answer)
    setFailed(false)
    const outcome = await answerWindow(sid, number, answer)
    if (outcome === 'mismatch') {
      setSending(null)
      setMismatched(true)
      return
    }
    if (outcome === 'failed') {
      setSending(null)
      setFailed(true)
      return
    }
    // sent, closed and stale all end this window's dialog; a newer window keeps the topbar button
    onClose()
  }

  // The backdrop closes it; a tap inside the dialog does not.
  const handleOverlayClick = (e) => {
    if (e.target === e.currentTarget && onClose) onClose()
  }

  return (
    <div className="permission-window-overlay" onClick={handleOverlayClick} data-testid="permission-window-dialog">
      <div className="permission-window-dialog">
        <div className="permission-window-titlebar">
          <span className="permission-window-title">
            🔐 {t('permission_window.title')}
            <span className="permission-window-tool" data-testid="permission-window-tool">{view.toolName}</span>
          </span>
          {view.position && (
            <span className="permission-window-position" data-testid="permission-window-position">
              {t('permission_window.position', view.position)}
            </span>
          )}
          {onClose && (
            <button type="button" className="permission-window-close" onClick={onClose} aria-label={t('common.close')}>
              ×
            </button>
          )}
        </div>
        <div className="permission-window-body">
          {view.original ? (
            <>
              <div className="permission-window-rewritten" data-testid="permission-window-rewritten">
                {t('permission_window.rewritten')}
              </div>
              <WindowInput fields={view.running} label={t('permission_window.input_running')} testId="permission-window-running" />
              <WindowInput fields={view.original} label={t('permission_window.input_original')} testId="permission-window-original" />
            </>
          ) : (
            <WindowInput fields={view.running} testId="permission-window-running" />
          )}
        </div>
        {inTerminal && (
          <div className="permission-window-failed" role="status" data-testid="permission-window-in-terminal">
            {t('permission_window.answer_in_terminal')}
          </div>
        )}
        {failed && (
          <div className="permission-window-failed" role="alert" data-testid="permission-window-failed">
            {t('permission_window.send_failed')}
          </div>
        )}
        <div className="permission-window-choices">
          {['allow', 'deny'].map(answer => (
            <button
              key={answer}
              className={`permission-window-choice ${sending === answer ? 'sending' : ''}`}
              disabled={!!sending || inTerminal}
              onClick={() => handle(answer)}
              data-testid="permission-window-answer"
              data-cpc-answer={answer}
            >
              {t(`permission_window.${answer}`)}
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}
