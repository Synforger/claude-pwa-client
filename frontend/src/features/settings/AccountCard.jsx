// 設定の画面の口座 1 つ分: 使用率と戻る時刻 (見るだけ)、 線 (曜日ごと・5 時間)、 線で止まっているタブと続ける口、
// 口座を固定しているタブと外す口。
import { useMemo, useState } from 'react'
import { useT } from '../../i18n/t.js'
import { NumberField, SaveBar } from './SettingsFields.jsx'
import { useCardSave } from './useCardSave.js'
import { useDraft } from './useDraft.js'
import {
  WEEKDAYS, accountDraftOf, accountPatch, formatMoment, formatPct, hasReset, todayKey,
} from './settingsDraft.js'

function UsageRow({ label, pct, resetsAt, nowSeconds }) {
  const t = useT()
  const reset = hasReset(resetsAt, nowSeconds)
  return (
    <div className="settings-usage-row">
      <span className="settings-usage-label">{label}</span>
      <span className="settings-usage-pct">{reset ? '0%' : formatPct(pct)}</span>
      <span className="settings-usage-reset">
        {typeof resetsAt === 'number'
          ? t(reset ? 'settings.usage.reset_done' : 'settings.usage.resets_at', { at: formatMoment(resetsAt) })
          : ''}
      </span>
    </div>
  )
}

function Usage({ usage, nowSeconds }) {
  const t = useT()
  if (!usage) return <div className="settings-dim">{t('settings.usage.none')}</div>
  return (
    <div className="settings-usage" data-testid="settings-usage">
      <UsageRow label={t('settings.usage.five_hour')} pct={usage.five_hour_pct}
        resetsAt={usage.five_hour_resets_at} nowSeconds={nowSeconds} />
      <UsageRow label={t('settings.usage.seven_day')} pct={usage.seven_day_pct}
        resetsAt={usage.seven_day_resets_at} nowSeconds={nowSeconds} />
    </div>
  )
}

function HeldTabs({ account, onContinue }) {
  const t = useT()
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  if (account.held_count === 0) return null
  const press = async () => {
    setBusy(true)
    setMessage('')
    try {
      const result = await onContinue(account.id)
      if (result.ok) {
        setMessage(result.failed.length
          ? t('settings.held.partly', { done: result.continued.length, failed: result.failed.length })
          : t('settings.held.done', { done: result.continued.length }))
      } else {
        setMessage(result.status === 409
          ? t('settings.held.still_at_line', { line: result.linePct ?? '' })
          : (result.reasons[0] || `HTTP ${result.status}`))
      }
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="settings-block" data-testid="settings-held">
      <div className="settings-block-title">{t('settings.held.title', { count: account.held_count })}</div>
      <div className="settings-block-row">
        <button type="button" className="modal-edit-btn" disabled={!account.can_continue || busy} onClick={press}
          data-testid="settings-continue">
          {t('settings.held.continue_all')}
        </button>
        {!account.can_continue && <span className="settings-note warn">{t('settings.held.blocked')}</span>}
      </div>
      {message && <div className="settings-note">{message}</div>}
    </div>
  )
}

function PinnedTabs({ account, onUnpin }) {
  const t = useT()
  if (account.pinned_tabs.length === 0) return null
  return (
    <div className="settings-block" data-testid="settings-pinned">
      <div className="settings-block-title">{t('settings.pinned.title')}</div>
      {account.pinned_tabs.map(tab => (
        <div className="settings-block-row" key={tab.id}>
          <span className="settings-tab-title">📌 {tab.title}</span>
          <button type="button" className="modal-cancel-btn" onClick={() => onUnpin(tab.id)}
            data-testid="settings-unpin">
            {t('settings.pinned.remove')}
          </button>
        </div>
      ))}
    </div>
  )
}

function modeLabel(t, account) {
  if (account.mode === 'fallback') return t('settings.account.mode_fallback', { to: account.fallback.to_display_name })
  return t(account.mode === 'hold' ? 'settings.account.mode_hold' : 'settings.account.mode_none')
}

/** `account` = GET /settings の accounts の 1 件。 onSave(patch) → { ok, reasons }、 onContinue(id)、 onUnpin(tabId)。 */
export default function AccountCard({ account, limits, nowSeconds, onSave, onContinue, onUnpin }) {
  const t = useT()
  const [draft, setDraft] = useDraft(accountDraftOf(account), JSON.stringify([account.mode, account.fallback, account.hold]))
  const { saving, reasons, saved, run } = useCardSave(onSave)
  const { patch, invalid } = useMemo(() => accountPatch(account, draft, limits), [account, draft, limits])
  const today = todayKey(new Date(nowSeconds * 1000))
  const setDay = (day, value) => setDraft(prev => ({ ...prev, days: { ...prev.days, [day]: value } }))
  const lineKind = account.mode === 'fallback' ? 'move' : 'stop'
  return (
    <section className="settings-card" data-testid={`settings-account-${account.id}`}>
      <header className="settings-card-head">
        <span className="settings-card-name">{account.display_name}</span>
        <span className="settings-badge" data-testid="settings-account-mode">{modeLabel(t, account)}</span>
      </header>
      <Usage usage={account.usage} nowSeconds={nowSeconds} />
      <div className="settings-block">
        <div className="settings-block-title">{t(`settings.lines.title_${lineKind}`)}</div>
        <div className="settings-note">{t(`settings.lines.hint_${lineKind}`)}</div>
        {account.mode === 'fallback' && (
          <NumberField
            label={t('settings.lines.five_hour')} suffix="%" value={draft.atPct}
            onChange={value => setDraft(prev => ({ ...prev, atPct: value }))}
            invalid={invalid.includes('atPct')} testId="settings-at-pct" title={t('settings.lines.five_hour_hint')}
          />
        )}
        <div className="settings-days" data-testid="settings-days">
          {WEEKDAYS.map(day => (
            <NumberField
              key={day} label={t(`settings.weekday.${day}`)} value={draft.days[day]} onChange={value => setDay(day, value)}
              invalid={invalid.includes(day)} placeholder={t('settings.lines.blank')} testId={`settings-day-${day}`}
              suffix={day === today ? '●' : undefined}
            />
          ))}
        </div>
        <SaveBar dirty={patch !== null} invalid={invalid.length > 0} saving={saving} saved={saved} reasons={reasons}
          onSave={() => run(patch)} testId="settings-account-save" />
      </div>
      <HeldTabs account={account} onContinue={onContinue} />
      <PinnedTabs account={account} onUnpin={onUnpin} />
    </section>
  )
}
