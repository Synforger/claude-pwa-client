// 設定の画面の入力 → 差分の変換と表示の整形 (= settingsDraft.js)。 規則は backend/settings/settings_fields.py と同じ。
import { describe, it, expect } from 'vitest'
import {
  WEEKDAYS, accountDraftOf, accountPatch, agentDraftOf, agentPatch, childLimitPatch, formatMoment, formatPct,
  hasReset, liftLaterDays, lineRule, parseField, reasonsOf, ruleMessage, titlePatch, todayKey, usageBar,
} from '../../../src/features/settings/settingsDraft.js'
import { AGENT, LIMITS, PERSONAL, WORK } from './fixtures.js'

describe('parseField', () => {
  it.each([
    ['70', { min: 1, max: 100 }, { ok: true, value: 70 }],
    [' 70 ', { min: 1, max: 100 }, { ok: true, value: 70 }],
    ['', { min: 1, max: 100 }, { ok: true, value: null }],
    ['  ', { min: 1, max: 100 }, { ok: true, value: null }],
    ['0', { min: 1, max: 100 }, { ok: false, value: null }],
    ['101', { min: 1, max: 100 }, { ok: false, value: null }],
    ['7.5', { min: 1, max: 100 }, { ok: false, value: null }],
    ['7.5', { min: 1, max: 100, whole: false }, { ok: true, value: 7.5 }],
    ['-3', { min: 0 }, { ok: false, value: null }],
    ['abc', { min: 0 }, { ok: false, value: null }],
    ['1e3', { min: 0 }, { ok: false, value: null }],
  ])('%j with %j', (text, rule, expected) => {
    expect(parseField(text, rule)).toEqual(expected)
  })
})

describe('accountPatch', () => {
  it('has no patch while nothing changed', () => {
    expect(accountPatch(WORK, accountDraftOf(WORK), LIMITS)).toEqual({ patch: null, invalid: [] })
  })

  it('sends the 5-hour line and the changed days of a fallback account, and only those', () => {
    const draft = accountDraftOf(WORK)
    draft.atPct = '90'
    draft.days.tue = '76'
    draft.days.mon = ''
    expect(accountPatch(WORK, draft, LIMITS).patch).toEqual({
      accounts: { work: { fallback: { at_pct: 90, seven_day_at_pct: { tue: 76, mon: null } } } },
    })
  })

  it('sends the days of a hold account under `hold`, and a blank day as null', () => {
    const draft = accountDraftOf(PERSONAL)
    draft.days.sat = ''
    draft.days.fri = '94'
    expect(accountPatch(PERSONAL, draft, LIMITS).patch).toEqual({
      accounts: { personal: { hold: { seven_day_at_pct: { sat: null, fri: 94 } } } },
    })
  })

  it('creates a hold for an account that has neither line', () => {
    const none = { ...PERSONAL, mode: 'none', hold: null }
    const draft = accountDraftOf(none)
    draft.days.mon = '80'
    expect(accountPatch(none, draft, LIMITS).patch).toEqual({
      accounts: { personal: { hold: { seven_day_at_pct: { mon: 80 } } } },
    })
  })

  it('names the fields that are out of range and sends nothing', () => {
    const draft = accountDraftOf(WORK)
    draft.atPct = '0'
    draft.days.wed = '101'
    expect(accountPatch(WORK, draft, LIMITS)).toEqual({ patch: null, invalid: ['atPct', 'wed'] })
  })

  it('does not let the 5-hour line of a fallback account be blank', () => {
    const draft = accountDraftOf(WORK)
    draft.atPct = ''
    expect(accountPatch(WORK, draft, LIMITS).invalid).toEqual(['atPct'])
  })

  it('sends the width ahead of the line of a fallback account, and a blank as null (= no width)', () => {
    const draft = accountDraftOf(WORK)
    draft.ahead = '5'
    expect(accountPatch(WORK, draft, LIMITS).patch).toEqual({ accounts: { work: { fallback: { ahead_pct: 5 } } } })
    const withWidth = { ...WORK, fallback: { ...WORK.fallback, ahead_pct: 5 } }
    const blank = accountDraftOf(withWidth)
    blank.ahead = ''
    expect(accountPatch(withWidth, blank, LIMITS).patch).toEqual({ accounts: { work: { fallback: { ahead_pct: null } } } })
  })

  it('takes a width from 0 to 50 and names a width outside it', () => {
    const draft = accountDraftOf(WORK)
    for (const ok of ['0', '50']) {
      draft.ahead = ok
      expect(accountPatch(WORK, draft, LIMITS).invalid).toEqual([])
    }
    for (const bad of ['51', '-1', '2.5', 'x']) {
      draft.ahead = bad
      expect(accountPatch(WORK, draft, LIMITS)).toEqual({ patch: null, invalid: ['ahead'] })
    }
  })

  it('sends the line of the 5 hours of a hold account under `hold`, and a blank as null (= no line)', () => {
    const draft = accountDraftOf(PERSONAL)
    draft.fiveHour = '95'
    expect(accountPatch(PERSONAL, draft, LIMITS).patch).toEqual({
      accounts: { personal: { hold: { five_hour_at_pct: 95 } } },
    })
    const withLine = { ...PERSONAL, hold: { ...PERSONAL.hold, five_hour_at_pct: 95 } }
    const blank = accountDraftOf(withLine)
    expect(blank.fiveHour).toBe('95')
    blank.fiveHour = ''
    expect(accountPatch(withLine, blank, LIMITS).patch).toEqual({
      accounts: { personal: { hold: { five_hour_at_pct: null } } },
    })
  })

  it('names a line of the 5 hours of a hold account that is out of range', () => {
    const draft = accountDraftOf(PERSONAL)
    for (const bad of ['0', '101', '9.5']) {
      draft.fiveHour = bad
      expect(accountPatch(PERSONAL, draft, LIMITS)).toEqual({ patch: null, invalid: ['fiveHour'] })
    }
  })

  it('has the fields of a fallback account blank for a hold account and the other way round', () => {
    expect(accountDraftOf(PERSONAL)).toMatchObject({ atPct: '', ahead: '', fiveHour: '' })
    expect(accountDraftOf(WORK)).toMatchObject({ atPct: '95', ahead: '0', fiveHour: '' })
  })

  it('reads the table of the account in the order of the week', () => {
    expect(Object.keys(accountDraftOf(PERSONAL).days)).toEqual(WEEKDAYS)
    expect(accountDraftOf(PERSONAL).days).toMatchObject({ mon: '70', tue: '', sat: '100' })
  })
})

describe('agentPatch', () => {
  it('has no patch while nothing changed', () => {
    expect(agentPatch(AGENT, agentDraftOf(AGENT), LIMITS)).toEqual({ patch: null, invalid: [] })
  })

  it('sends the sleep minutes and the rollover numbers that changed, nested as config.json is', () => {
    const draft = { ...agentDraftOf(AGENT), sleep: '30', idleContext: '35.5', working: '' }
    expect(agentPatch(AGENT, draft, LIMITS).patch).toEqual({
      agents: { agent_a: { sleep: { minutes: 30 }, rollover: { working: { context_pct: null }, idle: { context_pct: 35.5 } } } },
    })
  })

  it('turns sleep off with a blank field', () => {
    expect(agentPatch(AGENT, { ...agentDraftOf(AGENT), sleep: '' }, LIMITS).patch).toEqual({
      agents: { agent_a: { sleep: { minutes: null } } },
    })
  })

  it.each([
    [{ sleep: '0' }, 'sleep'],
    [{ sleep: '1.5' }, 'sleep'],
    [{ working: '101' }, 'working'],
    [{ idleContext: '0' }, 'idleContext'],
    [{ idleMinutes: '0' }, 'idleMinutes'],
    [{ idleMinutes: 'x' }, 'idleMinutes'],
  ])('refuses %j', (change, field) => {
    expect(agentPatch(AGENT, { ...agentDraftOf(AGENT), ...change }, LIMITS)).toEqual({ patch: null, invalid: [field] })
  })
})

describe('childLimitPatch and titlePatch', () => {
  it('sends the limit that changed, null for blank, and refuses what is not a whole number', () => {
    expect(childLimitPatch(5, '5')).toEqual({ patch: null, invalid: [] })
    expect(childLimitPatch(5, '3')).toEqual({ patch: { child_sessions_max: 3 }, invalid: [] })
    expect(childLimitPatch(5, '0')).toEqual({ patch: { child_sessions_max: 0 }, invalid: [] })
    expect(childLimitPatch(5, '')).toEqual({ patch: { child_sessions_max: null }, invalid: [] })
    expect(childLimitPatch(5, '2.5')).toEqual({ patch: null, invalid: ['childSessionsMax'] })
    expect(childLimitPatch(5, '-1')).toEqual({ patch: null, invalid: ['childSessionsMax'] })
  })

  it('sends the title that changed and null for blank', () => {
    expect(titlePatch('通知', '通知')).toEqual({ patch: null })
    expect(titlePatch('通知', ' お知らせ ')).toEqual({ patch: { notification_title: 'お知らせ' } })
    expect(titlePatch('通知', '  ')).toEqual({ patch: { notification_title: null } })
  })
})

describe('display helpers', () => {
  it('formats a usage as a rounded percentage and a missing one as a dash', () => {
    expect(formatPct(40.4)).toBe('40%')
    expect(formatPct(null)).toBe('—')
    expect(formatPct(undefined)).toBe('—')
  })

  it('formats a moment in the local time of the device', () => {
    expect(formatMoment(new Date(2026, 10, 9, 7, 5).getTime() / 1000)).toBe('11/9 07:05')
    expect(formatMoment(null)).toBe('—')
  })

  it('tells a window that has reset from one that has not', () => {
    expect(hasReset(100, 200)).toBe(true)
    expect(hasReset(200, 200)).toBe(true)
    expect(hasReset(300, 200)).toBe(false)
    expect(hasReset(null, 200)).toBe(false)
  })

  it('names today by the order the backend uses (Monday first)', () => {
    expect(todayKey(new Date(2026, 10, 9))).toBe('mon')
    expect(todayKey(new Date(2026, 10, 14))).toBe('sat')
    expect(todayKey(new Date(2026, 10, 15))).toBe('sun')
  })

  it('takes the reasons of a refused update, else the message', () => {
    expect(reasonsOf({ detail: { code: 'settings_rejected', params: { reasons: ['a: x', 'b: y'] } } })).toEqual(['a: x', 'b: y'])
    expect(reasonsOf({ detail: 'Not found' })).toEqual(['Not found'])
    expect(reasonsOf({ detail: { message: '失敗' } })).toEqual(['失敗'])
    expect(reasonsOf(null)).toEqual([])
  })
})

describe('liftLaterDays (the days count from Sunday: sun, mon, tue, wed, thu, fri, sat)', () => {
  const RANGE = lineRule(LIMITS)
  const week = (over = {}) => ({ mon: '50', tue: '47', wed: '59', thu: '', fri: '30', sat: '100', sun: '20', ...over })

  it('lifts the later days that are below the new value up to it, and leaves the higher ones and the earlier ones', () => {
    // monday 35 -> 50: tuesday 47 -> 50, wednesday 59 stays, friday 30 -> 50, sunday (before monday) stays
    const { days, lifted } = liftLaterDays(week(), 'mon', '35', RANGE)
    expect(lifted).toEqual(['tue', 'fri'])
    expect(days).toMatchObject({ mon: '50', tue: '50', wed: '59', thu: '', fri: '50', sat: '100', sun: '20' })
  })

  it('does not move anything when the line is lowered', () => {
    const before = week({ mon: '30' })
    expect(liftLaterDays(before, 'mon', '50', RANGE)).toEqual({ days: before, lifted: [] })
  })

  it('does not move anything when the value did not change', () => {
    expect(liftLaterDays(week(), 'mon', '50', RANGE).lifted).toEqual([])
  })

  it('does not lift a blank day', () => {
    const { days } = liftLaterDays(week(), 'mon', '35', RANGE)
    expect(days.thu).toBe('')
  })

  it('does not lift a day that holds something out of range', () => {
    const { days, lifted } = liftLaterDays(week({ tue: 'abc', fri: '300' }), 'mon', '35', RANGE)
    expect(days.tue).toBe('abc')
    expect(days.fri).toBe('300')
    expect(lifted).toEqual([])
  })

  it('counts sunday first: editing sunday lifts monday to saturday, editing saturday lifts nothing', () => {
    const lifted = liftLaterDays(week({ sun: '60', mon: '10', sat: '5' }), 'sun', '20', RANGE)
    expect(lifted.lifted).toEqual(['mon', 'tue', 'wed', 'fri', 'sat'])
    expect(lifted.days).toMatchObject({ sun: '60', mon: '60', tue: '60', wed: '60', thu: '', fri: '60', sat: '60' })
    expect(liftLaterDays(week({ sat: '90' }), 'sat', '10', RANGE).lifted).toEqual([])
  })

  it('does not move anything when the new value is blank or out of range', () => {
    expect(liftLaterDays(week({ mon: '' }), 'mon', '35', RANGE).lifted).toEqual([])
    expect(liftLaterDays(week({ mon: '101' }), 'mon', '35', RANGE).lifted).toEqual([])
    expect(liftLaterDays(week({ mon: 'x' }), 'mon', '35', RANGE).lifted).toEqual([])
  })

  it('lifts when a blank day gets a value, since that is not lowering a line', () => {
    expect(liftLaterDays(week({ mon: '50' }), 'mon', '', RANGE).lifted).toEqual(['tue', 'fri'])
  })

  it('does not change what it was given', () => {
    const given = week()
    liftLaterDays(given, 'mon', '35', RANGE)
    expect(given).toEqual(week())
  })
})

describe('usageBar and ruleMessage', () => {
  const NOW = 1000
  it('puts the line on the bar and says it is over when the usage reaches it', () => {
    expect(usageBar({ pct: 46, resetsAt: NOW + 10, line: 47, nowSeconds: NOW })).toEqual({ pct: 46, line: 47, over: false })
    expect(usageBar({ pct: 47, resetsAt: NOW + 10, line: 47, nowSeconds: NOW })).toEqual({ pct: 47, line: 47, over: true })
  })

  it('reads a window that has reset as 0, not over, and a day without a line as no line', () => {
    expect(usageBar({ pct: 96, resetsAt: NOW - 1, line: 95, nowSeconds: NOW })).toEqual({ pct: 0, line: 95, over: false })
    expect(usageBar({ pct: 96, resetsAt: NOW + 1, line: null, nowSeconds: NOW })).toEqual({ pct: 96, line: null, over: false })
    expect(usageBar({ pct: null, resetsAt: null, line: 50, nowSeconds: NOW }).pct).toBe(0)
  })

  it('names the message of a rule by its kind and range', () => {
    expect(ruleMessage({ min: 1, max: 100 })).toEqual({ key: 'settings.error.whole_range', vars: { min: 1, max: 100 } })
    expect(ruleMessage({ min: 1, max: 100, whole: false }).key).toBe('settings.error.number_range')
    expect(ruleMessage({ min: 0 }).key).toBe('settings.error.whole_min')
    expect(ruleMessage({ min: 1, whole: false }).key).toBe('settings.error.number_min')
  })
})
