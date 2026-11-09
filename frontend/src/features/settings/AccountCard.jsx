// 設定の画面の口座 1 つ分: タブの数と使用率 (バーに今日の線を重ねる)、 線 (曜日ごと・5 時間・先回りの幅)、 線で止まっている
// タブと続ける口、 口座を固定しているタブと外す口。
import { useEffect, useMemo, useRef, useState } from 'react'
import { useT } from '../../i18n/t.js'
import { NumberField, SaveBar } from './SettingsFields.jsx'
import { useReportDirty } from './SettingsDirty.js'
import { useCardSave } from './useCardSave.js'
import { useDraft } from './useDraft.js'
import {
  WEEKDAYS, accountDraftOf, accountPatch, aheadRule, formatMoment, formatPct, hasReset, liftLaterDays, lineRule, ruleMessage,
  todayKey, usageBar,
} from './settingsDraft.js'

// 持ち上げた欄を光らせる長さ (= SettingsScreen.css の settings-lift-flash と同じ)。
const LIFT_FLASH_MS = 1600

function UsageRow({ label, bar, resetsAt, nowSeconds, testId }) {
  const t = useT()
  const reset = hasReset(resetsAt, nowSeconds)
  return (
    <div className="settings-usage-row" data-testid={testId}>
      <span className="settings-usage-label">{label}</span>
      <div className="settings-bar" role="meter" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(bar.pct)}>
        <div className={`settings-bar-fill${bar.over ? ' over' : ''}`} style={{ width: `${bar.pct}%` }} data-testid="settings-bar-fill" />
        {bar.line !== null && (
          <span className="settings-bar-line" style={{ marginLeft: `${bar.line}%` }} title={t('settings.usage.line', { line: bar.line })}
            data-testid="settings-bar-line" />
        )}
      </div>
      <span className={`settings-usage-pct${bar.over ? ' over' : ''}`}>{formatPct(bar.pct)}</span>
      <span className="settings-usage-reset">
        {typeof resetsAt === 'number'
          ? t(reset ? 'settings.usage.reset_done' : 'settings.usage.resets_at', { at: formatMoment(resetsAt) })
          : ''}
      </span>
    </div>
  )
}

function Usage({ fiveBar, sevenBar, usage, nowSeconds }) {
  const t = useT()
  if (!usage) return <div className="settings-dim">{t('settings.usage.none')}</div>
  return (
    <div className="settings-usage" data-testid="settings-usage">
      <UsageRow label={t('settings.usage.five_hour')} bar={fiveBar} resetsAt={usage.five_hour_resets_at} nowSeconds={nowSeconds}
        testId="settings-usage-five" />
      <UsageRow label={t('settings.usage.seven_day')} bar={sevenBar} resetsAt={usage.seven_day_resets_at} nowSeconds={nowSeconds}
        testId="settings-usage-seven" />
    </div>
  )
}

function Tabs({ tabs }) {
  const t = useT()
  return (
    <div className="settings-note" data-testid="settings-tab-counts">
      {t('settings.account.tabs', { total: tabs.total, running: tabs.running, pinned: tabs.pinned, held: tabs.held })}
    </div>
  )
}

function HeldTabs({ account, blocked, onContinue }) {
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
        {!account.can_continue && (
          <span className="settings-note warn" data-testid="settings-continue-blocked">
            {t('settings.held.blocked', { pct: formatPct(blocked.pct), line: blocked.line ?? '—' })}
          </span>
        )}
      </div>
      {message && <div className="settings-note" data-testid="settings-continue-result">{message}</div>}
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
  useReportDirty(`account:${account.id}`, patch !== null || invalid.length > 0)
  const today = todayKey(new Date(nowSeconds * 1000))
  const setDay = (day, value) => setDraft(prev => ({ ...prev, days: { ...prev.days, [day]: value } }))

  // 欄に入った時の文字。 欄を離れた時に、 これと比べて上げたか下げたかを決める (= 打っている途中の文字では決めない)。
  // 入った時の文字が無い時 (= 欄に入らずに値が変わった時) は、 保存されている値と比べる。
  const startedWith = useRef({})
  // 持ち上げた曜日と値。 欄を一瞬光らせ、 注を次の書き換えまで出す (= 保存の前に、 何が動いたか見えるように)。
  const [lift, setLift] = useState(null)
  useEffect(() => {
    if (!lift) return undefined
    const timer = setTimeout(() => setLift(prev => (prev === lift ? { ...prev, flash: false } : prev)), LIFT_FLASH_MS)
    return () => clearTimeout(timer)
  }, [lift])
  const leaveDay = (day) => {
    const { days, lifted } = liftLaterDays(draft.days, day, startedWith.current[day] ?? accountDraftOf(account).days[day], lineRule(limits))
    if (lifted.length) {
      setDraft(prev => ({ ...prev, days }))
      setLift({ days: lifted, value: days[lifted[0]], flash: true })
    }
  }

  // 使用率のバーに重ねる今日の線は、 backend が今効かせている値 (= 入力の途中の値ではない)。
  const usage = account.usage
  const lines = account.mode === 'fallback'
    ? { five: account.fallback.at_pct, seven: account.fallback.seven_day_today_pct }
    : { five: account.hold?.five_hour_at_pct ?? null, seven: account.hold?.today_pct ?? null }
  const fiveBar = usageBar({ pct: usage?.five_hour_pct, resetsAt: usage?.five_hour_resets_at, line: lines.five, nowSeconds })
  const sevenBar = usageBar({ pct: usage?.seven_day_pct, resetsAt: usage?.seven_day_resets_at, line: lines.seven, nowSeconds })

  const lineKind = account.mode === 'fallback' ? 'move' : 'stop'
  const rangeError = (() => { const m = ruleMessage(lineRule(limits)); return t(m.key, m.vars) })()
  const aheadError = (() => { const m = ruleMessage(aheadRule(limits)); return t(m.key, m.vars) })()
  // 止めた後に「続ける」 が押せない理由に出す使用率は、 線に届いている窓 (= 5 時間か 7 日) のもの。
  const blocked = fiveBar.over ? { pct: fiveBar.pct, line: lines.five } : { pct: sevenBar.pct, line: lines.seven }
  return (
    <section className="settings-card" data-testid={`settings-account-${account.id}`}>
      <header className="settings-card-head">
        <span className="settings-card-name" data-testid="settings-account-name">{account.display_name}</span>
        <span className="settings-badge" data-testid="settings-account-mode">{modeLabel(t, account)}</span>
      </header>
      <Tabs tabs={account.tabs} />
      <Usage fiveBar={fiveBar} sevenBar={sevenBar} usage={usage} nowSeconds={nowSeconds} />
      <div className="settings-block">
        <div className="settings-block-title">{t(`settings.lines.title_${lineKind}`)}</div>
        <div className="settings-note">{t(`settings.lines.hint_${lineKind}`)}</div>
        {account.mode === 'fallback' ? (
          <>
            <NumberField
              label={t('settings.lines.five_hour')} suffix="%" value={draft.atPct}
              onChange={value => setDraft(prev => ({ ...prev, atPct: value }))}
              invalid={invalid.includes('atPct')} error={rangeError} testId="settings-at-pct" title={t('settings.lines.five_hour_hint')}
            />
            <NumberField
              label={t('settings.lines.ahead')} suffix="%" value={draft.ahead} placeholder="0"
              onChange={value => setDraft(prev => ({ ...prev, ahead: value }))}
              invalid={invalid.includes('ahead')} error={aheadError} testId="settings-ahead-pct" title={t('settings.lines.ahead_hint')}
            />
          </>
        ) : (
          <NumberField
            label={t('settings.lines.five_hour')} suffix="%" value={draft.fiveHour} placeholder={t('settings.lines.blank')}
            onChange={value => setDraft(prev => ({ ...prev, fiveHour: value }))}
            invalid={invalid.includes('fiveHour')} error={rangeError} testId="settings-five-hour-pct"
            title={t('settings.lines.five_hour_stop_hint')}
          />
        )}
        <div className="settings-days" data-testid="settings-days">
          {WEEKDAYS.map(day => (
            <NumberField
              key={day} label={t(`settings.weekday.${day}`)} value={draft.days[day]} onChange={value => setDay(day, value)}
              onFocus={() => { startedWith.current[day] = draft.days[day]; setLift(null) }} onBlur={() => leaveDay(day)}
              lifted={lift?.flash === true && lift.days.includes(day)} today={day === today}
              invalid={invalid.includes(day)} error={rangeError} placeholder={t('settings.lines.blank')}
              testId={`settings-day-${day}`}
            />
          ))}
        </div>
        {lift && (
          <div className="settings-note ok" data-testid="settings-lifted">
            {t('settings.lines.lifted', { days: lift.days.map(day => t(`settings.weekday.${day}`)).join('・'), value: lift.value })}
          </div>
        )}
        <SaveBar dirty={patch !== null} invalid={invalid.length > 0} saving={saving} saved={saved} reasons={reasons}
          onSave={() => run(patch)} testId="settings-account-save" />
      </div>
      <HeldTabs account={account} blocked={blocked} onContinue={onContinue} />
      <PinnedTabs account={account} onUnpin={onUnpin} />
    </section>
  )
}
