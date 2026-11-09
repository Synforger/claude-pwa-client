// @vitest-environment jsdom
//
// 設定の画面の口座の card: 使用率の表示、 線の入力と保存、 線で止まったタブを続ける口、 口座の固定を外す口。
import { describe, it, expect, afterEach, beforeEach, vi } from 'vitest'
import { render, cleanup, fireEvent, waitFor } from '@testing-library/react'
import AccountCard from '../../../src/features/settings/AccountCard.jsx'
import { setLang } from '../../../src/state/locale.js'
import { LIMITS, PERSONAL, WORK } from './fixtures.js'

beforeEach(() => setLang('ja'))
afterEach(cleanup)

const NOW = 1_900_000_000
const props = (account, over = {}) => ({
  account, limits: LIMITS, nowSeconds: NOW, onSave: vi.fn(async () => ({ ok: true })),
  onContinue: vi.fn(), onUnpin: vi.fn(), ...over,
})
const show = (account, over) => {
  const p = props(account, over)
  return { ...render(<AccountCard {...p} />), ...p }
}
const type = (getByTestId, id, value) => fireEvent.change(getByTestId(id), { target: { value } })

describe('usage', () => {
  it('shows the usage of the 5 hours and the 7 days with the time they reset', () => {
    const { getByTestId } = show(WORK)
    const usage = getByTestId('settings-usage').textContent
    expect(usage).toContain('30%')
    expect(usage).toContain('40%')
    expect(usage).toContain('に戻る')
  })

  it('reads a window that has already reset as 0 and says it was reset', () => {
    const reset = { ...WORK, usage: { ...WORK.usage, five_hour_resets_at: NOW - 60, five_hour_pct: 96 } }
    const { getByTestId } = show(reset)
    expect(getByTestId('settings-usage').textContent).toContain('0%')
    expect(getByTestId('settings-usage').textContent).toContain('に戻った')
  })

  it('says so when no usage was recorded', () => {
    const { queryByTestId, container } = show({ ...WORK, usage: null })
    expect(queryByTestId('settings-usage')).toBeNull()
    expect(container.textContent).toContain('使用率の記録がありません')
  })
})

describe('the account in the card', () => {
  it('shows the name set in the configuration and how many tabs run on the account, split by what they are doing', () => {
    const { getByTestId } = show(WORK)
    expect(getByTestId('settings-account-name').textContent).toBe('Work')
    expect(getByTestId('settings-tab-counts').textContent).toBe('タブ 3 個: 動いている 2・固定 1・線で止まっている 0')
    cleanup()
    expect(show(PERSONAL).getByTestId('settings-tab-counts').textContent).toContain('線で止まっている 2')
  })
})

describe('usage bars', () => {
  it('draws each bar to the usage and puts the line of today on it', () => {
    const { getByTestId } = show(WORK)
    const five = getByTestId('settings-usage-five')
    expect(five.querySelector('[data-testid=settings-bar-fill]').style.width).toBe('30%')
    expect(five.querySelector('[data-testid=settings-bar-line]').style.marginLeft).toBe('95%')
    const seven = getByTestId('settings-usage-seven')
    expect(seven.querySelector('[data-testid=settings-bar-line]').style.marginLeft).toBe('95%')
  })

  it('turns the bar red when the usage is at the line, for the 5 hours and for the 7 days alike', () => {
    const over = { ...WORK, usage: { ...WORK.usage, five_hour_pct: 96, seven_day_pct: 96 } }
    const { getByTestId } = show(over)
    for (const row of ['settings-usage-five', 'settings-usage-seven']) {
      expect(getByTestId(row).querySelector('.settings-bar-fill').className).toContain('over')
      expect(getByTestId(row).querySelector('.settings-usage-pct').className).toContain('over')
    }
  })

  it('has no line on the 7 days of a hold account on a day without a line, and none on its 5 hours', () => {
    const { getByTestId } = show({ ...PERSONAL, hold: { ...PERSONAL.hold, today_pct: null } })
    expect(getByTestId('settings-usage-seven').querySelector('[data-testid=settings-bar-line]')).toBeNull()
    expect(getByTestId('settings-usage-five').querySelector('[data-testid=settings-bar-line]')).toBeNull()
  })
})

describe('the field of today', () => {
  it('marks only the field of the day of the week of the screen\'s clock', () => {
    const monday = new Date(2026, 10, 9, 12).getTime() / 1000
    const { getByTestId, container } = show(WORK, { nowSeconds: monday })
    expect(container.querySelectorAll('.settings-field.today').length).toBe(1)
    expect(getByTestId('settings-day-mon').closest('.settings-field').className).toContain('today')
    expect(getByTestId('settings-day-tue').closest('.settings-field').className).not.toContain('today')
  })
})

describe('what is wrong with a value', () => {
  it('says, under the field and before save is pressed, what the field takes', () => {
    const { getByTestId } = show(WORK)
    type(getByTestId, 'settings-day-thu', '101')
    const field = getByTestId('settings-day-thu').closest('.settings-field')
    expect(field.querySelector('.settings-field-error').textContent).toBe('1〜100 の整数で入れてください')
    expect(getByTestId('settings-account-save').disabled).toBe(true)
  })
})

describe('lifting the later days', () => {
  const edit = (getByTestId, day, value) => {
    fireEvent.focus(getByTestId(`settings-day-${day}`))
    type(getByTestId, `settings-day-${day}`, value)
    fireEvent.blur(getByTestId(`settings-day-${day}`))
  }

  it('lifts the later days below the new value when the field is left, marks them and says what moved', () => {
    const account = { ...WORK, fallback: { ...WORK.fallback, seven_day_at_pct: { mon: 35, tue: 47, wed: 59, sun: 20 } } }
    const { getByTestId, container } = show(account)
    edit(getByTestId, 'mon', '50')
    expect(getByTestId('settings-day-tue').value).toBe('50')
    expect(getByTestId('settings-day-wed').value).toBe('59')
    expect(getByTestId('settings-day-sun').value).toBe('20')
    expect(getByTestId('settings-lifted').textContent).toContain('火')
    expect(getByTestId('settings-lifted').textContent).toContain('50%')
    expect(container.querySelectorAll('.settings-field.lifted').length).toBe(1)
  })

  it('compares with the saved value when the field changed without being entered', () => {
    const account = { ...WORK, fallback: { ...WORK.fallback, seven_day_at_pct: { mon: 35, tue: 47 } } }
    const { getByTestId } = show(account)
    type(getByTestId, 'settings-day-mon', '50')
    fireEvent.blur(getByTestId('settings-day-mon'))
    expect(getByTestId('settings-day-tue').value).toBe('50')
  })

  it('waits for the field to be left: typing does not move anything', () => {
    const account = { ...WORK, fallback: { ...WORK.fallback, seven_day_at_pct: { mon: 35, tue: 47 } } }
    const { getByTestId, queryByTestId } = show(account)
    fireEvent.focus(getByTestId('settings-day-mon'))
    type(getByTestId, 'settings-day-mon', '5')
    type(getByTestId, 'settings-day-mon', '50')
    expect(getByTestId('settings-day-tue').value).toBe('47')
    expect(queryByTestId('settings-lifted')).toBeNull()
  })

  it('saves the values on the screen, the lifted ones too', async () => {
    const account = { ...WORK, fallback: { ...WORK.fallback, seven_day_at_pct: { mon: 35, tue: 47, wed: 59 } } }
    const { getByTestId, onSave } = show(account)
    edit(getByTestId, 'mon', '50')
    fireEvent.click(getByTestId('settings-account-save'))
    await waitFor(() => expect(onSave).toHaveBeenCalled())
    expect(onSave).toHaveBeenCalledWith({ accounts: { work: { fallback: { seven_day_at_pct: { mon: 50, tue: 50 } } } } })
  })

  it('does not move the later days when the line is lowered', () => {
    const account = { ...WORK, fallback: { ...WORK.fallback, seven_day_at_pct: { mon: 50, tue: 40 } } }
    const { getByTestId, queryByTestId } = show(account)
    edit(getByTestId, 'mon', '30')
    expect(getByTestId('settings-day-tue').value).toBe('40')
    expect(queryByTestId('settings-lifted')).toBeNull()
  })
})

describe('lines', () => {
  it('shows the 5-hour line only for an account that has a fallback, and a day per weekday', () => {
    const fallback = show(WORK)
    expect(fallback.getByTestId('settings-at-pct').value).toBe('95')
    expect(fallback.getByTestId('settings-day-mon').value).toBe('70')
    expect(fallback.getByTestId('settings-day-tue').value).toBe('')
    cleanup()
    const hold = show(PERSONAL)
    expect(hold.queryByTestId('settings-at-pct')).toBeNull()
    expect(hold.getByTestId('settings-day-sat').value).toBe('100')
  })

  it('shows the width ahead of the line for a fallback account, and the 5-hour line for a hold account', () => {
    const fallback = show({ ...WORK, fallback: { ...WORK.fallback, ahead_pct: 5 } })
    expect(fallback.getByTestId('settings-ahead-pct').value).toBe('5')
    expect(fallback.queryByTestId('settings-five-hour-pct')).toBeNull()
    cleanup()
    const hold = show({ ...PERSONAL, hold: { ...PERSONAL.hold, five_hour_at_pct: 95 } })
    expect(hold.getByTestId('settings-five-hour-pct').value).toBe('95')
    expect(hold.queryByTestId('settings-ahead-pct')).toBeNull()
    cleanup()
    expect(show(PERSONAL).getByTestId('settings-five-hour-pct').value).toBe('')
  })

  it('saves a new width ahead of the line and nothing else', async () => {
    const { getByTestId, onSave } = show(WORK)
    type(getByTestId, 'settings-ahead-pct', '5')
    fireEvent.click(getByTestId('settings-account-save'))
    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1))
    expect(onSave).toHaveBeenCalledWith({ accounts: { work: { fallback: { ahead_pct: 5 } } } })
  })

  it('saves a new 5-hour line of a hold account and nothing else', async () => {
    const { getByTestId, onSave } = show(PERSONAL)
    type(getByTestId, 'settings-five-hour-pct', '95')
    fireEvent.click(getByTestId('settings-account-save'))
    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1))
    expect(onSave).toHaveBeenCalledWith({ accounts: { personal: { hold: { five_hour_at_pct: 95 } } } })
  })

  it('refuses a width above 50: the field is marked, the range is shown and save stays off', () => {
    const { getByTestId, container } = show(WORK)
    type(getByTestId, 'settings-ahead-pct', '51')
    expect(getByTestId('settings-account-save').disabled).toBe(true)
    expect(container.querySelector('.settings-field.invalid')).not.toBeNull()
    expect(container.textContent).toContain('0〜50 の整数で入れてください')
  })

  it('puts the 5-hour line of a hold account on the 5-hour bar', () => {
    const { getByTestId } = show({ ...PERSONAL, hold: { ...PERSONAL.hold, five_hour_at_pct: 95 } })
    expect(getByTestId('settings-usage-five').querySelector('[data-testid=settings-bar-line]').style.marginLeft).toBe('95%')
  })

  it('keeps save off until a line changes, then saves the change and nothing else', async () => {
    const { getByTestId, onSave } = show(PERSONAL)
    const save = getByTestId('settings-account-save')
    expect(save.disabled).toBe(true)
    type(getByTestId, 'settings-day-fri', '94')
    expect(save.disabled).toBe(false)
    fireEvent.click(save)
    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1))
    expect(onSave).toHaveBeenCalledWith({ accounts: { personal: { hold: { seven_day_at_pct: { fri: 94 } } } } })
  })

  it('refuses a value out of range: the field is marked and save stays off', () => {
    const { getByTestId, container } = show(WORK)
    type(getByTestId, 'settings-at-pct', '101')
    expect(getByTestId('settings-account-save').disabled).toBe(true)
    expect(container.querySelector('.settings-field.invalid')).not.toBeNull()
    expect(container.textContent).toContain('入力が範囲外です')
  })

  it('shows the reasons the backend gave when it refuses the update', async () => {
    const onSave = vi.fn(async () => ({ ok: false, status: 400, reasons: ['accounts.work.hold: refused'] }))
    const { getByTestId, findByRole } = show(WORK, { onSave })
    type(getByTestId, 'settings-day-wed', '80')
    fireEvent.click(getByTestId('settings-account-save'))
    expect((await findByRole('alert')).textContent).toContain('accounts.work.hold: refused')
  })
})

describe('tabs the line stopped', () => {
  it('shows nothing for an account without stopped tabs', () => {
    expect(show(WORK).queryByTestId('settings-held')).toBeNull()
  })

  it('shows how many are stopped and continues them all', async () => {
    const onContinue = vi.fn(async () => ({ ok: true, continued: ['a', 'b'], failed: [] }))
    const { getByTestId } = show(PERSONAL, { onContinue })
    expect(getByTestId('settings-held').textContent).toContain('2')
    fireEvent.click(getByTestId('settings-continue'))
    await waitFor(() => expect(onContinue).toHaveBeenCalledWith('personal'))
    await waitFor(() => expect(getByTestId('settings-held').textContent).toContain('2 個のタブに続けてと頼みました'))
  })

  it('names the 5 hours as what blocks continuing when they are the window at the line', () => {
    const account = { ...PERSONAL, can_continue: false, hold: { ...PERSONAL.hold, five_hour_at_pct: 95 },
      usage: { ...PERSONAL.usage, five_hour_pct: 96 } }
    expect(show(account).getByTestId('settings-continue-blocked').textContent).toBe('今 96% / 今日の線 95%')
  })

  it('cannot be pressed while the usage is at the line', () => {
    const { getByTestId } = show({ ...PERSONAL, can_continue: false })
    expect(getByTestId('settings-continue').disabled).toBe(true)
    expect(getByTestId('settings-continue-blocked').textContent).toBe('今 55% / 今日の線 70%')
  })

  it('says the line when the backend refuses with 409', async () => {
    const onContinue = vi.fn(async () => ({ ok: false, status: 409, reasons: [], linePct: 70 }))
    const { getByTestId } = show(PERSONAL, { onContinue })
    fireEvent.click(getByTestId('settings-continue'))
    await waitFor(() => expect(getByTestId('settings-held').textContent).toContain('(70%)'))
  })

  it('says how many did not take the message', async () => {
    const onContinue = vi.fn(async () => ({ ok: true, continued: ['a'], failed: ['b'] }))
    const { getByTestId } = show(PERSONAL, { onContinue })
    fireEvent.click(getByTestId('settings-continue'))
    await waitFor(() => expect(getByTestId('settings-held').textContent).toContain('1 個は届きませんでした'))
  })
})

describe('tabs pinned to the account', () => {
  it('lists them and unpins one by its id', () => {
    const { getByTestId, onUnpin } = show(WORK)
    expect(getByTestId('settings-pinned').textContent).toContain('要のタブ')
    fireEvent.click(getByTestId('settings-unpin'))
    expect(onUnpin).toHaveBeenCalledWith('ses_p')
  })

  it('shows nothing when no tab is pinned', () => {
    expect(show(PERSONAL).queryByTestId('settings-pinned')).toBeNull()
  })
})
