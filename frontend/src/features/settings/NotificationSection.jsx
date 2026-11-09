// 設定の画面の「通知」。 この端末の通知のオン・オフ (= 端末だけの設定) と、 通知の題 (= config.json の notification_title)。
import { useMemo } from 'react'
import { useT } from '../../i18n/t.js'
import { usePushSubscription } from '../push-notify/usePushSubscription.js'
import { SaveBar } from './SettingsFields.jsx'
import { useCardSave } from './useCardSave.js'
import { useDraft } from './useDraft.js'
import { titlePatch } from './settingsDraft.js'

function PushToggle() {
  const t = useT()
  const { pushEnabled, pushBroken, pushBusy, pushAvailable, handleTogglePush } = usePushSubscription()
  if (!pushAvailable) return <div className="settings-dim">{t('settings.notification.unavailable')}</div>
  return (
    <button type="button" className="modal-edit-btn settings-wide" onClick={handleTogglePush} disabled={pushBusy}
      data-testid="settings-push-toggle">
      {pushEnabled ? t('drawer.push.on') : pushBroken ? t('drawer.push.broken') : t('drawer.push.off')}
    </button>
  )
}

function TitleField({ value, onSave }) {
  const t = useT()
  const [text, setText] = useDraft(value, value)
  const { saving, reasons, saved, run } = useCardSave(onSave)
  const { patch } = useMemo(() => titlePatch(value, text), [value, text])
  return (
    <div className="settings-block">
      <label className="settings-field settings-field-text">
        <span className="settings-field-label">{t('settings.notification.title_label')}</span>
        <span className="settings-field-input">
          <input type="text" value={text} onChange={e => setText(e.target.value)} data-testid="settings-title-input" />
        </span>
      </label>
      <div className="settings-note">{t('settings.notification.title_hint')}</div>
      <SaveBar dirty={patch !== null} invalid={false} saving={saving} saved={saved} reasons={reasons}
        onSave={() => run(patch)} testId="settings-title-save" />
    </div>
  )
}

export default function NotificationSection({ view, onSave }) {
  const t = useT()
  return (
    <section className="settings-section" data-testid="settings-notification">
      <h3>{t('settings.notification.title')}</h3>
      <section className="settings-card">
        <div className="settings-block"><PushToggle /></div>
        <TitleField value={view.notification_title} onSave={onSave} />
      </section>
    </section>
  )
}
