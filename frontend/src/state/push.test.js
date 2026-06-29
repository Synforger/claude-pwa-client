import { describe, it, expect, beforeEach } from 'vitest'
import {
  getSnapshot,
  subscribe,
  setPushState,
  setPushAvailable,
  setPushEnabled,
  setPushBroken,
  setPushBusy,
  _resetForTest,
} from './push.js'

// Phase J-2 (= 2026-06-29、 ADR-026 末尾「将来 task」 2 件目) の contract test。
// 旧実装は usePushSubscription 内 useState で state を持っていたため、 hook が複数 instance
// で並走すると state が分裂する欠陥があった。 本 store は module singleton として 1 経路を
// 保証する。 「複数 subscribe で同 state を読む」「setter が全 subscriber に通知」「同値 set は
// snapshot reference を維持」 の 3 契約を保証する。

describe('state/push.js setter contract (= singleton store)', () => {
  beforeEach(() => { _resetForTest() })

  it('INITIAL = available:false / enabled:false / broken:false / busy:false', () => {
    expect(getSnapshot()).toEqual({
      available: false, enabled: false, broken: false, busy: false,
    })
  })

  it('individual setter は対応 field のみ更新', () => {
    setPushAvailable(true)
    expect(getSnapshot()).toEqual({ available: true, enabled: false, broken: false, busy: false })
    setPushEnabled(true)
    expect(getSnapshot()).toEqual({ available: true, enabled: true, broken: false, busy: false })
    setPushBroken(true)
    expect(getSnapshot()).toEqual({ available: true, enabled: true, broken: true, busy: false })
    setPushBusy(true)
    expect(getSnapshot()).toEqual({ available: true, enabled: true, broken: true, busy: true })
  })

  it('setPushState は patch 形式で複数 field を 1 経路で更新', () => {
    setPushState({ available: true, enabled: true })
    expect(getSnapshot()).toEqual({ available: true, enabled: true, broken: false, busy: false })
  })

  it('同値 setter は snapshot reference を変えない (= subscriber 通知抑止の契約)', () => {
    setPushAvailable(true)
    const snap1 = getSnapshot()
    setPushAvailable(true)
    expect(getSnapshot()).toBe(snap1)
    setPushAvailable(false)
    expect(getSnapshot()).not.toBe(snap1)
  })

  it('複数 subscribe は同一 store の同一 snapshot を読む (= singleton 保証)', () => {
    const seen1 = []
    const seen2 = []
    const unsub1 = subscribe((s) => seen1.push(s))
    const unsub2 = subscribe((s) => seen2.push(s))

    setPushEnabled(true)
    setPushBusy(true)

    expect(seen1).toHaveLength(2)
    expect(seen2).toHaveLength(2)
    // 全 subscriber が同一 snapshot を受ける = state が分裂してない
    expect(seen1[0]).toBe(seen2[0])
    expect(seen1[1]).toBe(seen2[1])
    expect(getSnapshot()).toBe(seen1[1])

    unsub1()
    unsub2()
  })

  it('subscribe 解除後は listener が呼ばれない', () => {
    const seen = []
    const unsub = subscribe((s) => seen.push(s))
    setPushEnabled(true)
    expect(seen).toHaveLength(1)
    unsub()
    setPushEnabled(false)
    expect(seen).toHaveLength(1)
  })

  it('_resetForTest は INITIAL に戻す', () => {
    setPushState({ available: true, enabled: true, broken: true, busy: true })
    _resetForTest()
    expect(getSnapshot()).toEqual({
      available: false, enabled: false, broken: false, busy: false,
    })
  })
})
