// state/ui.js (= overlay / scroll / keyboard / viewModes singleton) の契約 test。
//
// 急所は「同値 set は同一参照を返す」 bailout 契約: これが壊れると subscriber 全 component
// が毎 set で再 render される (= 性能退行が静かに入る)。
import { describe, it, expect } from 'vitest'
import {
  getSnapshot,
  setOverlay,
  setScroll,
  setModifier,
  addPressedKey,
  removePressedKey,
  addFlashingKey,
  removeFlashingKey,
  setViewMode,
  hydrate,
} from './ui.js'

describe('state/ui — bailout 契約 (= 同値 set は同一参照)', () => {
  it.each([
    ['setOverlay', () => setOverlay('drawer', true), () => setOverlay('drawer', true)],
    ['setModifier', () => setModifier('shift', true), () => setModifier('shift', true)],
    ['addPressedKey', () => addPressedKey('a'), () => addPressedKey('a')],
    ['setViewMode', () => setViewMode('s1', 'terminal'), () => setViewMode('s1', 'terminal')],
    ['addFlashingKey', () => addFlashingKey('f'), () => addFlashingKey('f')],
  ])('%s: 2 回目の同値 set で snapshot 参照が変わらない', (_name, first, second) => {
    first()
    const snap = getSnapshot()
    second()
    expect(getSnapshot()).toBe(snap)
  })

  it('remove 系: 存在しない key の remove は no-op (= 参照不変)', () => {
    removePressedKey('zz')
    const snap = getSnapshot()
    removePressedKey('zz')
    removeFlashingKey('zz')
    expect(getSnapshot()).toBe(snap)
  })
})

describe('state/ui — 更新セマンティクス', () => {
  it('overlay は key 単位で独立更新される', () => {
    setOverlay('menu', true)
    setOverlay('previewPath', '/tmp/x.md')
    const { overlays } = getSnapshot()
    expect(overlays.menu).toBe(true)
    expect(overlays.previewPath).toBe('/tmp/x.md')
    setOverlay('menu', false)
    expect(getSnapshot().overlays.previewPath).toBe('/tmp/x.md')
  })

  it('pressedKeys は Set を複製して更新する (= 前 snapshot を汚さない)', () => {
    addPressedKey('x')
    const before = getSnapshot().keyboard.pressedKeys
    addPressedKey('y')
    expect(before.has('y')).toBe(false)
    expect(getSnapshot().keyboard.pressedKeys.has('y')).toBe(true)
    removePressedKey('x')
    removePressedKey('y')
  })

  it('setScroll は部分 patch をマージする', () => {
    setScroll({ showScrollBtn: true })
    setScroll({ hasNew: true })
    const { scroll } = getSnapshot()
    expect(scroll.showScrollBtn).toBe(true)
    expect(scroll.hasNew).toBe(true)
    setScroll({ showScrollBtn: false, hasNew: false })
  })

  it('hydrate は object 以外を無視する', () => {
    const snap = getSnapshot()
    hydrate(null)
    hydrate('junk')
    expect(getSnapshot()).toBe(snap)
    hydrate({ viewModes: { s9: 'terminal' } })
    expect(getSnapshot().viewModes.s9).toBe('terminal')
  })
})
