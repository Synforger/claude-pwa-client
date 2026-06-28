import { useSyncExternalStore, useMemo } from 'react'
import {
  subscribe as subscribeSessions,
  getSnapshot as getSessionsSnapshot,
} from '../../state/sessions.js'
import { setOverlay } from '../../state/ui.js'
import { useStatus } from '../status-bar/useStatus.js'
import '../file-tree/FileTreePanel.css'
import './TasksModal.css'

const STATUS_MARK = {
  pending: '○',
  in_progress: '◉',
  completed: '✓',
  deleted: '×',
}

const STATUS_CLASS = {
  pending: 'task-pending',
  in_progress: 'task-doing',
  completed: 'task-done',
  deleted: 'task-deleted',
}

// 📋 ボタンから開く専用パネル。 backend が attachment task_reminder の content を
// agent_status.tasks に流し込んだものをそのまま縦リストで見せる。 タップで描画 / 編集
// する経路はなく、 現状把握専用。
// W2 Phase E-2 (= 2026-06-29): props 自己解決化 (= activeSession を sessions store から派生、
// useStatus 直呼出で tasks を解決、 onClose は setOverlay 直書き)。
export default function TasksModal() {
  const sessionsSnap = useSyncExternalStore(subscribeSessions, getSessionsSnapshot)
  const activeId = sessionsSnap.activeId
  const activeSession = useMemo(
    () => sessionsSnap.sessions.find(s => s.id === activeId) || null,
    [sessionsSnap.sessions, activeId],
  )
  const status = useStatus(activeSession)
  const tasks = status?.tasks || []
  const onClose = () => setOverlay('tasks', false)

  const list = Array.isArray(tasks) ? tasks : []
  const counts = list.reduce((acc, t) => {
    const s = t?.status || 'pending'
    acc[s] = (acc[s] || 0) + 1
    return acc
  }, {})
  const total = list.length
  const doing = counts.in_progress || 0
  const done = counts.completed || 0

  return (
    <div className="tree-overlay" onClick={onClose} data-testid="tasks-modal">
      <div className="tree-panel" onClick={e => e.stopPropagation()}>
        <div className="tree-header">
          <div className="tree-nav">
            <span className="tree-path">📋 tasks</span>
            <span className="tasks-summary">
              {total === 0 ? 'no tasks' : `${done}/${total} done · ${doing} doing`}
            </span>
          </div>
          <button className="modal-close" onClick={onClose}>✕</button>
        </div>
        <div className="tree-body">
          {list.length === 0 && (
            <div className="dim tree-loading">
              このセッションでは TaskCreate でまだタスクが登録されていません。
            </div>
          )}
          {list.map(t => {
            const st = t?.status || 'pending'
            return (
              <div key={t.id ?? t.subject} className={`task-row ${STATUS_CLASS[st] || ''}`}>
                <span className="task-mark">{STATUS_MARK[st] || '?'}</span>
                <div className="task-body">
                  <div className="task-subject">
                    <span className="task-id">#{t.id ?? '?'}</span>
                    {t.subject || '(no subject)'}
                  </div>
                  {t.activeForm && st === 'in_progress' && (
                    <div className="task-active">{t.activeForm}</div>
                  )}
                  {t.description && (
                    <div className="task-desc">{t.description}</div>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
