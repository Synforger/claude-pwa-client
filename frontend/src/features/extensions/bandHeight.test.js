// 拡張の帯の高さ (= %) の範囲と、 ドラッグ量からの換算と、 保存値の読み戻しの検査。
import { describe, it, expect, beforeEach } from 'vitest'
import {
  BAND_MIN_PCT, BAND_MAX_PCT, BAND_DEFAULT_PCT,
  clampBandPct, pctAfterDrag, loadBandPct, saveBandPct,
} from './bandHeight.js'

const store = new Map()
globalThis.localStorage = {
  getItem: (k) => (store.has(k) ? store.get(k) : null),
  setItem: (k, v) => { store.set(k, String(v)) },
  removeItem: (k) => { store.delete(k) },
}

describe('features/extensions — band height', () => {
  beforeEach(() => store.clear())

  it('keeps the height within 15-70% and falls back to 30% for junk', () => {
    expect(clampBandPct(5)).toBe(BAND_MIN_PCT)
    expect(clampBandPct(95)).toBe(BAND_MAX_PCT)
    expect(clampBandPct(42)).toBe(42)
    expect(clampBandPct('40')).toBe(BAND_DEFAULT_PCT)
    expect(clampBandPct(NaN)).toBe(BAND_DEFAULT_PCT)
  })

  it('converts a drag distance into a share of the screen', () => {
    // 800px の画面で 80px 下へ = +10%
    expect(pctAfterDrag(30, 80, 800)).toBe(40)
    expect(pctAfterDrag(30, -80, 800)).toBe(20)
    // 範囲外へ引っ張っても端で止まる
    expect(pctAfterDrag(30, 2000, 800)).toBe(BAND_MAX_PCT)
    expect(pctAfterDrag(30, 100, 0)).toBe(30)
  })

  it('reads back what was saved, and the default when nothing or junk is stored', () => {
    expect(loadBandPct()).toBe(BAND_DEFAULT_PCT)
    saveBandPct(55)
    expect(loadBandPct()).toBe(55)
    store.set('cpc.extensions.bandPct', '"tall"')
    expect(loadBandPct()).toBe(BAND_DEFAULT_PCT)
    saveBandPct(99)
    expect(loadBandPct()).toBe(BAND_MAX_PCT)
  })
})
