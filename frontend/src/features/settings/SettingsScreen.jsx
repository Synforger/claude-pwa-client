import { useCallback, useRef, useState } from 'react'
import { setOverlay } from '../../state/ui.js'
import { useEscape } from '../../_common/useEscape.js'
import ConfirmDialog from '../../_common/ConfirmDialog.jsx'
import { useT } from '../../i18n/t.js'
import { setAccountPinned } from '../session-drawer/useSessions.js'
import AccountsSection from './AccountsSection.jsx'
import AgentsSection from './AgentsSection.jsx'
import MachineSection from './MachineSection.jsx'
import NotificationSection from './NotificationSection.jsx'
import { DirtyContext } from './SettingsDirty.js'
import { useSettings } from './useSettings.js'
import '../../_common/Modal.css'
import './SettingsScreen.css'

// ⚙ のメニューの「設定」 から開く画面。 口座の線・タブの眠りと入れ替え・通知・この機械を 1 か所で見て変える。
// 値の真値は backend の config.json (= GET /settings で読み、 PUT /settings で書く)。 変えた値は次の見回りから効く。
// タブごとの設定 (= 口座の固定・通知・名前) は会話の一覧の ⋯ メニューに残る。
export default function SettingsScreen() {
  const t = useT()
  const { view, loadedAt, error, save, continueTabs, reload } = useSettings()
  // 保存していない変更がある card (= 変えたままの card の名前の集まり)。 1 つでも在る間は、 閉じる前に訊く。
  const dirty = useRef(new Set())
  const [askDiscard, setAskDiscard] = useState(false)
  const reportDirty = useCallback((id, isDirty) => {
    if (isDirty) dirty.current.add(id)
    else dirty.current.delete(id)
  }, [])
  const close = useCallback(() => setOverlay('settings', false), [])
  const onClose = useCallback(() => (dirty.current.size > 0 ? setAskDiscard(true) : close()), [close])
  useEscape(onClose)

  const unpin = useCallback(async (tabId) => {
    await setAccountPinned(tabId, false)
    await reload()
  }, [reload])

  return (
    <DirtyContext.Provider value={reportDirty}>
      <div className="modal-overlay settings-overlay" onClick={onClose}>
        <div className="modal settings-modal" onClick={e => e.stopPropagation()} data-testid="settings-screen">
          <div className="modal-header">
            <span className="settings-title">{t('settings.title')}</span>
            <div className="modal-actions">
              <button className="modal-close" onClick={onClose} aria-label={t('common.close')}>✕</button>
            </div>
          </div>
          <div className="modal-body settings-body">
            {error && <div className="settings-error" role="alert">{t('settings.load_error')}</div>}
            {!view && !error && <span className="settings-dim">{t('settings.loading')}</span>}
            {view && (
              <>
                <AccountsSection view={view} nowSeconds={loadedAt} onSave={save} onContinue={continueTabs} onUnpin={unpin} />
                <AgentsSection view={view} onSave={save} />
                <NotificationSection view={view} onSave={save} />
                <MachineSection view={view} />
              </>
            )}
          </div>
          <ConfirmDialog
            open={askDiscard}
            text={t('settings.discard_confirm')}
            onCancel={() => setAskDiscard(false)}
            onConfirm={close}
          />
        </div>
      </div>
    </DirtyContext.Provider>
  )
}
