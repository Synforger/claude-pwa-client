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

  it('cannot be pressed while the usage is at the line', () => {
    const { getByTestId } = show({ ...PERSONAL, can_continue: false })
    expect(getByTestId('settings-continue').disabled).toBe(true)
    expect(getByTestId('settings-held').textContent).toContain('使用率がまだ今日の線以上です')
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
