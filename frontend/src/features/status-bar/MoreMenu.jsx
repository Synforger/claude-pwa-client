import { useCallback, useMemo, useRef, useState, useSyncExternalStore } from 'react'
import {
  subscribe as subscribeUi,
  getSnapshot as getUiSnapshot,
  setOverlay,
  setViewMode,
} from '../../state/ui.js'
import { subscribe as subscribeSessions, getSnapshot as getSessionsSnapshot } from '../../state/sessions.js'
import { bumpAttachmentPicker } from '../../state/ephemeral.js'
import { refetchChat } from '../chat/useChatStream.js'
import { useOutsideClick } from '../../hooks/useOutsideClick.js'
import { useT } from '../../i18n/t.js'

// ⋯ メニュー: ファイル添付 / ファイルツリー / ⌨↔💬 表示切替 / チャット再取得 / セッション終了 の集約。
// 置き場はステータスバーの右端 (= 2026-09-23 に上部バーから移設、 上部バーの右端は拡張のボタンが使う)。
// セッションが無い時は出さない。 開いているセッションと表示モードは自前で store から引く
// (= ADR-010 props 自己解決契約)。 状態 (open) はローカル useState、 outside click で閉じる。
// ファイル添付は fileInputRef を直接触らず ephemeral の attachmentPickerBump を上げ、
// ChatPanel 側 subscribe で fileInputRef.click() を発火する疎結合設計 (= ChatPanel が持つ
// useAttachments の hidden <input> をここから知らずに済ませる)。
export default function MoreMenu() {
  const ui = useSyncExternalStore(subscribeUi, getUiSnapshot)
  const activeSid = useSyncExternalStore(subscribeSessions, () => getSessionsSnapshot().activeId) || null
  const activeViewMode = useMemo(
    () => (activeSid ? (ui.viewModes[activeSid] || 'chat') : 'chat'),
    [activeSid, ui.viewModes],
  )
  const setActiveViewMode = useCallback((mode) => {
    if (activeSid) setViewMode(activeSid, mode)
  }, [activeSid])
  if (!activeSid) return null
  return <MoreMenuBody activeViewMode={activeViewMode} setActiveViewMode={setActiveViewMode} />
}

function MoreMenuBody({ activeViewMode, setActiveViewMode }) {
  const [open, setOpen] = useState(false)
  const rootRef = useRef(null)
  useOutsideClick(rootRef, () => setOpen(false))
  const close = useCallback(() => setOpen(false), [])
  const t = useT()
  return (
    <span className="more-menu-root" ref={rootRef}>
      <button
        className="more-menu-btn"
        onClick={() => setOpen(v => !v)}
        aria-label={t('topbar.menu')}
        title={t('topbar.menu')}
        data-testid="more-menu-toggle"
      >
        ⋯
      </button>
      {open && (
        <div className="more-menu-popup">
          <button
            className="more-menu-item"
            onClick={() => { bumpAttachmentPicker(); close() }}
            data-testid="more-menu-file-attach"
          >
            {t('topbar.menu.file_attach')}
          </button>
          <button
            className="more-menu-item"
            onClick={() => { setOverlay('treeOpen', '~'); close() }}
            data-testid="more-menu-file-tree"
          >
            {t('topbar.menu.file_tree')}
          </button>
          <button
            className="more-menu-item"
            onClick={() => {
              setActiveViewMode(activeViewMode === 'terminal' ? 'chat' : 'terminal')
              close()
            }}
            data-testid="view-toggle"
          >
            {activeViewMode === 'terminal' ? t('topbar.menu.chat_view') : t('topbar.menu.terminal_view')}
          </button>
          {/* チャット再取得: SSE 取りこぼし / offset ズレで表示が実 JSONL と食い違った時の
              手動復旧。 実装は features/chat (= refetchChat module export、 endSession と同じ
              流儀) で、 Topbar は呼ぶだけ。 */}
          <button
            className="more-menu-item"
            onClick={() => { refetchChat(); close() }}
            data-testid="refetch-chat"
          >
            {t('topbar.menu.refetch_chat')}
          </button>
          {/* 2026-07-03: Language toggle は SessionDrawer ⋯ に移設。 通知 / アプリ更新と同じ
              「PWA レベル設定」 の並びに寄せた方が意味的に自然。 */}
          <button
            className="more-menu-item"
            onClick={() => { setOverlay('confirmEnd', true); close() }}
            style={{ color: '#ff5f57' }}
          >
            {t('topbar.menu.end_session')}
          </button>
        </div>
      )}
    </span>
  )
}
