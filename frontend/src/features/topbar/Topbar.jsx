// topbar 経路の自己完結 owner (= W2 Phase F-3、 2026-06-29)。 旧 AppShell.jsx の `<header className="topbar">`
// block を物理移送、 ロジック改変ゼロ。 各 button の onClick は内部で setOverlay 直呼出 + 必要な store
// (= sessions / ui / status) は自前 subscribe で解決する (= ADR-010 props 自己解決契約)。
//
// AppShell からは <Topbar /> 1 行配置のみ。 常時 mount component (= overlay でない) なので
// registerFeature 経由で配線、 Component lazy spec は不要 (= main bundle 同梱で OK、
// features/__contracts__/no-lazy-component-static-import.test.js の Component spec 件数は不変)。

import { useSyncExternalStore, useMemo, useCallback, useState, useRef } from 'react'
import {
  subscribe as subscribeUi,
  getSnapshot as getUiSnapshot,
  setOverlay,
  setViewMode,
} from '../../state/ui.js'
import {
  subscribe as subscribeSessions,
  getSnapshot as getSessionsSnapshot,
} from '../../state/sessions.js'
import { bumpAttachmentPicker } from '../../state/ephemeral.js'
import { useOutsideClick } from '../../hooks/useOutsideClick.js'
import { useT } from '../../i18n/t.js'
import { useStatus } from '../status-bar/useStatus.js'
import { useMoonlightAvailable } from '../screenshare/useMoonlightAvailable.js'

export default function Topbar() {
  const ui = useSyncExternalStore(subscribeUi, getUiSnapshot)
  const sessionsState = useSyncExternalStore(subscribeSessions, getSessionsSnapshot)
  const t = useT()

  const activeSession = useMemo(
    () => sessionsState.sessions.find(s => s.id === sessionsState.activeId) || null,
    [sessionsState.sessions, sessionsState.activeId],
  )
  const activeSid = activeSession?.id || null
  const activeViewMode = useMemo(
    () => (activeSid ? (ui.viewModes[activeSid] || 'chat') : 'chat'),
    [activeSid, ui.viewModes],
  )
  const setActiveViewMode = useCallback((mode) => {
    if (!activeSid) return
    setViewMode(activeSid, mode)
  }, [activeSid])

  // topbar の 📑 ボタン (= plan 承認待ち) は status.pending_plan で出すかを判定し、 click で
  // ui.overlays.planOpen を立てる。 PlanApprovalBubble 本体の render + auto-close は ChatPanel が担う。
  const status = useStatus(activeSession)
  const moonlightAvailable = useMoonlightAvailable()

  return (
    <header className="topbar">
      <button className="hamburger" onClick={() => setOverlay('drawer', true)} aria-label={t('topbar.drawer_toggle')} data-testid="drawer-toggle">
        ☰
      </button>
      <span className="topbar-title">{activeSession?.title || t('topbar.no_session')}</span>
      {/* terminal モード時の chat 復帰ボタン: ⋯メニュー経由が hit test 等で詰まっても
          ここから確実に戻れるよう topbar に独立表示。 chat モード時は出さない。 */}
      {activeViewMode === 'terminal' && activeSid && (
        <button
          className="topbar-icon-btn"
          onClick={() => setActiveViewMode('chat')}
          aria-label={t('topbar.back_to_chat')}
          title={t('topbar.back_to_chat')}
        >
          💬
        </button>
      )}
      {/* topbar 右側のアイコン群。 並びは左→右で ⭐ お気に入り → 📋 タスク →
          🤖 サブエージェント → (📑 plan 承認、 条件付き) → 🖥 モニター。 */}
      {activeViewMode === 'chat' && activeSid && (
        <button
          className="topbar-icon-btn"
          onClick={() => setOverlay('favs', true)}
          aria-label={t('topbar.favorites_label')}
          title={t('topbar.favorites')}
          data-testid="favorites-open-button"
        >
          ⭐
        </button>
      )}
      {activeViewMode === 'chat' && activeSid && (
        <button
          className="topbar-icon-btn"
          onClick={() => setOverlay('tasks', true)}
          aria-label={t('topbar.tasks_label')}
          title={t('topbar.tasks')}
          data-testid="tasks-open-button"
        >
          📋
        </button>
      )}
      {activeViewMode === 'chat' && activeSid && (
        <button
          className="topbar-icon-btn"
          onClick={() => { setOverlay('subagentsFocus', null); setOverlay('subagents', true) }}
          aria-label={t('topbar.subagents_label')}
          title={t('topbar.subagents')}
          data-testid="subagents-open-button"
        >
          🤖
        </button>
      )}
      {/* ExitPlanMode 承認待ち: 🤖 の隣に常駐する 📑 ボタン。 pending_plan がある時のみ表示、
          脈動ドットで承認待ちを示し、 タップで PlanApprovalBubble (= ChatPanel 内) を開く
          (= ui.overlays.planOpen 経由)。 */}
      {activeViewMode === 'chat' && activeSid && status?.pending_plan && (
        <button
          className="topbar-icon-btn topbar-plan-btn"
          onClick={() => setOverlay('planOpen', true)}
          aria-label={t('topbar.plan_approval_label')}
          title={t('topbar.plan_approval')}
          data-testid="plan-approval-open-button"
        >
          📑<span className="topbar-plan-dot" />
        </button>
      )}
      {moonlightAvailable && (
        <button
          className={`screen-toggle ${ui.overlays.desktopOpen ? 'active' : ''}`}
          onClick={() => setOverlay('desktopOpen', !ui.overlays.desktopOpen)}
          aria-label={t('topbar.screenshare_label')}
          title={ui.overlays.desktopOpen ? t('topbar.screenshare_close') : t('topbar.screenshare_open')}
          data-testid="screenshare-toggle"
        >
          🖥
        </button>
      )}
      {activeSid && (
        <TopbarMoreMenu
          activeViewMode={activeViewMode}
          setActiveViewMode={setActiveViewMode}
        />
      )}
    </header>
  )
}

// ⋯ メニュー: ファイル添付 / ファイルツリー / ⌨↔💬 表示切替 / セッション終了 の集約。
// 旧 ChatInput 右端の ⋯ からここへ物理移送 (= 2026-07-02、 入力行を Send + 停止 の 2 slot に
// 純化するため)。 状態 (menuOpen) はローカル useState、 outside click / ESC で閉じる。
// ファイル添付は fileInputRef を直接触らず ephemeral の attachmentPickerBump を上げ、
// ChatPanel 側 subscribe で fileInputRef.click() を発火する疎結合設計 (= ChatPanel が持つ
// useAttachments の hidden <input> を Topbar から知らずに済ませる、 ADR-010 props 自己解決契約)。
function TopbarMoreMenu({ activeViewMode, setActiveViewMode }) {
  const [open, setOpen] = useState(false)
  const rootRef = useRef(null)
  useOutsideClick(rootRef, () => setOpen(false))
  const close = useCallback(() => setOpen(false), [])
  const t = useT()
  return (
    <div className="topbar-more-root" ref={rootRef}>
      <button
        className="topbar-more-btn"
        onClick={() => setOpen(v => !v)}
        aria-label={t('topbar.menu')}
        title={t('topbar.menu')}
        data-testid="topbar-more-toggle"
      >
        ⋯
      </button>
      {open && (
        <div className="topbar-more-popup">
          <button
            className="topbar-more-item"
            onClick={() => { bumpAttachmentPicker(); close() }}
          >
            {t('topbar.menu.file_attach')}
          </button>
          <button
            className="topbar-more-item"
            onClick={() => { setOverlay('treeOpen', '~'); close() }}
          >
            {t('topbar.menu.file_tree')}
          </button>
          <button
            className="topbar-more-item"
            onClick={() => {
              setActiveViewMode(activeViewMode === 'terminal' ? 'chat' : 'terminal')
              close()
            }}
            data-testid="view-toggle"
          >
            {activeViewMode === 'terminal' ? t('topbar.menu.chat_view') : t('topbar.menu.terminal_view')}
          </button>
          {/* 2026-07-03: Language toggle は SessionDrawer ⋯ に移設。 通知 / アプリ更新と同じ
              「PWA レベル設定」 の並びに寄せた方が意味的に自然。 */}
          <button
            className="topbar-more-item"
            onClick={() => { setOverlay('confirmEnd', true); close() }}
            style={{ color: '#ff5f57' }}
          >
            {t('topbar.menu.end_session')}
          </button>
        </div>
      )}
    </div>
  )
}
