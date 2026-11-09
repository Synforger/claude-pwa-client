// 設定の画面の入力 → 差分の変換と表示の整形 (= settingsDraft.js)。 規則は backend/settings/settings_fields.py と同じ。
import { describe, it, expect } from 'vitest'
import {
  WEEKDAYS, accountDraftOf, accountPatch, agentDraftOf, agentPatch, childLimitPatch, formatMoment, formatPct,
  hasReset, parseField, reasonsOf, titlePatch, todayKey,
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
