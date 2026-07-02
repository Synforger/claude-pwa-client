// Bash / Monitor 由来の TaskNotification 用 raw 出力 modal。 subagent 経路 (= SubagentsModal で
// /task-transcript 構造化 render) と分離することで、 「サブエージェント一覧の内側に居るように
// 見える」 UX 混同を解消する (= 2026-07-03)。
//
// UI は最小: タイトル + 閉じるボタン + <pre> raw text (+ ローディング / エラー表記)。
// fetch は /task-output のみ (= subagent jsonl の transcript 化は要らない、 raw で十分)。
import { useState, useEffect, useSyncExternalStore } from 'react'
import { apiFetch } from '../../utils/api.js'
import { useEscape } from '../../hooks/useEscape.js'
import { useT } from '../../i18n/t.js'
import { translateHttpErrorDetail } from '../../utils/httpError.js'
import {
  subscribe as subscribeUi,
  getSnapshot as getUiSnapshot,
  setOverlay,
} from '../../state/ui.js'
import '../../shared/Modal.css'
import '../subagents/SubagentsModal.css'

export default function TaskOutputModal() {
  const ui = useSyncExternalStore(subscribeUi, getUiSnapshot)
  const path = ui.overlays.taskOutputPath
  const onClose = () => setOverlay('taskOutputPath', null)
  useEscape(onClose)
  if (!path) return null
  return <TaskOutputModalInner path={path} onClose={onClose} />
}

function TaskOutputModalInner({ path, onClose }) {
  const t = useT()
  const [content, setContent] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    const controller = new AbortController()
    setContent(null)
    setError(null)
    apiFetch(`/task-output?path=${encodeURIComponent(path)}`, { signal: controller.signal })
      .then(async r => {
        if (r.ok) {
          const data = await r.json()
          setContent(typeof data?.content === 'string' ? data.content : '')
          return
        }
        const d = await r.json().catch(() => ({}))
        throw new Error(translateHttpErrorDetail(d?.detail, `HTTP ${r.status}`))
      })
      .catch(e => { if (e.name !== 'AbortError') setError(e.message || t('file_preview.load_error')) })
    return () => controller.abort()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path])

  return (
    <div className="modal-overlay" onClick={onClose} data-testid="task-output-modal">
      <div className="modal" onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <span className="modal-path">{t('task_output.title')}</span>
          <div className="modal-actions">
            <button className="modal-close" onClick={onClose}>✕</button>
          </div>
        </div>
        <div className="modal-body">
          {error && <span className="error">{error}</span>}
          {content === null && !error && <span className="dim">{t('common.loading')}</span>}
          {content !== null && <pre className="sa-raw-output">{content || t('common.empty')}</pre>}
        </div>
      </div>
    </div>
  )
}
