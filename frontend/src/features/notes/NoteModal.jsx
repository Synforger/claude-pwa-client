import { useCallback, useEffect, useState, useSyncExternalStore } from 'react'
import {
  subscribe as subscribeSessions,
  getSnapshot as getSessionsSnapshot,
} from '../../state/sessions.js'
import { subscribe as subscribeMessages, getSnapshot as getMessagesSnapshot } from '../../state/messages.js'
import { setOverlay } from '../../state/ui.js'
import { apiFetch } from '../../utils/api.js'
import { translateHttpErrorDetail } from '../../utils/httpError.js'
import { useEscape } from '../../hooks/useEscape.js'
import { useT } from '../../i18n/t.js'
import ConfirmDialog from '../../shared/ConfirmDialog.jsx'
import MessageRenderer from '../chat/MessageRenderer.jsx'
import '../../shared/Modal.css'
import './NoteModal.css'

// 📋 から開く、 タブごとのメモ。
//
// 真値は host の file 1 本 (= GET / PUT /sessions/{sid}/note)。 そのタブのエージェントも同じ file を
// 直に書くので、 画面はここに写しを持たず、 開いた時と、 そのタブの会話が進むたびに読み直す。
// 見る時はチャットと同じ描き方 (= 書いてある path はタップで開く)、 書く時はただのテキスト欄。
// メモはそのタブの下書きで、 タブを消すと消える。
export default function NoteModal() {
  const t = useT()
  const sessionsSnap = useSyncExternalStore(subscribeSessions, getSessionsSnapshot)
  const activeId = sessionsSnap.activeId
  // このタブの会話の列を、 読み直しの合図にする: エージェントがメモを書けば、 その道具の行が必ず
  // 会話に足される (= 列は足されるたびに新しい配列になる)。 「今使っている道具」 は合図に使えない
  // (= 書き込みのような速い道具は、 始まりと終わりが同じ周期に入って画面まで届かない)。
  const messagesSnap = useSyncExternalStore(subscribeMessages, getMessagesSnapshot)
  const conversation = activeId ? messagesSnap[activeId] : undefined

  const [content, setContent] = useState(null)   // null = まだ読んでいない
  const [error, setError] = useState(null)
  const [editMode, setEditMode] = useState(false)
  const [editText, setEditText] = useState('')
  const [saving, setSaving] = useState(false)
  const [resetConfirm, setResetConfirm] = useState(false)

  const onClose = useCallback(() => setOverlay('notes', false), [])

  // 開いた時 / タブが変わった時 / 会話が進んだ時に読む。 書いている間は読み直さない
  // (= 手元の文を画面の下で差し替えない)。
  useEffect(() => {
    if (!activeId || editMode) return undefined
    const controller = new AbortController()
    apiFetch(`/sessions/${encodeURIComponent(activeId)}/note`, { signal: controller.signal })
      .then(r => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then(data => { setContent(typeof data.content === 'string' ? data.content : ''); setError(null) })
      .catch(e => { if (e.name !== 'AbortError') setError(t('notes.load_error')) })
    return () => controller.abort()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeId, conversation, editMode])

  // 別のタブへ移ったら、 前のタブの文を持ち越さない
  useEffect(() => {
    setContent(null)
    setEditMode(false)
    setResetConfirm(false)
    setError(null)
  }, [activeId])

  const write = useCallback(async (text) => {
    setSaving(true)
    setError(null)
    try {
      const res = await apiFetch(`/sessions/${encodeURIComponent(activeId)}/note`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: text }),
      })
      if (!res.ok) {
        const d = await res.json().catch(() => ({}))
        throw new Error(translateHttpErrorDetail(d.detail, `HTTP ${res.status}`))
      }
      setContent(text)
      setEditMode(false)
    } catch (e) {
      setError(t('notes.save_error', { detail: e.message }))
    } finally {
      setSaving(false)
    }
  }, [activeId, t])

  const handleEdit = () => { setEditText(content ?? ''); setError(null); setEditMode(true) }
  const handleCancel = () => { setEditMode(false); setError(null) }
  const handleReset = async () => { setResetConfirm(false); await write('') }
  // チャットと同じ: path をタップしたらプレビューで開く。 メモは畳む (= プレビューと同じ場所に重なるため)
  const handleOpenFile = useCallback((path) => {
    setOverlay('notes', false)
    setOverlay('previewPath', path)
  }, [])

  useEscape(() => {
    if (resetConfirm) setResetConfirm(false)
    else if (editMode) handleCancel()
    else onClose()
  })

  if (!activeId) return null

  return (
    <div className="modal-overlay modal-overlay-preview" onClick={editMode ? undefined : onClose} data-testid="notes-modal">
      <div className="modal" onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <span className="modal-path note-title">📋 {t('notes.title')}</span>
          <div className="modal-actions">
            {!editMode && content !== null && (
              <button className="modal-edit-btn" onClick={handleEdit} data-testid="notes-edit">{t('notes.edit')}</button>
            )}
            {!editMode && !!content && (
              <button className="modal-cancel-btn" onClick={() => setResetConfirm(true)} disabled={saving} data-testid="notes-reset">
                {t('notes.reset')}
              </button>
            )}
            {editMode && (
              <>
                <button className="modal-save-btn" onClick={() => write(editText)} disabled={saving} data-testid="notes-save">
                  {saving ? t('notes.saving') : t('notes.save')}
                </button>
                <button className="modal-cancel-btn" onClick={handleCancel} disabled={saving}>{t('common.cancel')}</button>
              </>
            )}
            {!editMode && <button className="modal-close" onClick={onClose}>✕</button>}
          </div>
        </div>
        <div className="modal-body" data-testid="notes-body">
          {error && <span className="error">{error}</span>}
          {editMode ? (
            <textarea
              className="file-editor note-editor"
              value={editText}
              onChange={e => setEditText(e.target.value)}
              spellCheck={false}
              autoFocus
              data-testid="notes-editor"
            />
          ) : content === null ? (
            !error && <span className="dim">{t('notes.loading')}</span>
          ) : content === '' ? (
            <p className="dim note-empty">{t('notes.empty')}</p>
          ) : (
            // 枠の見た目は markdown のファイルプレビューと同じ物 (= 見出し / 表 / コードの罫と余白)
            <div className="md-preview">
              <MessageRenderer text={content} onOpenFile={handleOpenFile} />
            </div>
          )}
        </div>
        <ConfirmDialog
          open={resetConfirm}
          text={t('notes.reset_confirm')}
          onCancel={() => setResetConfirm(false)}
          onConfirm={handleReset}
        />
      </div>
    </div>
  )
}
