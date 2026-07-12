// perfProbe (= 発熱調査 段階 2 の観測基盤) の契約 test。
import { describe, it, expect, beforeEach } from 'vitest'
import {
  recordPerfSample,
  drainPerfSamples,
  registerPerfContext,
  readPerfContext,
  _resetPerfProbe,
} from './perfProbe.js'

describe('perfProbe', () => {
  beforeEach(() => _resetPerfProbe())

  it('drain は所要時間の大きい順に top-N を返しリングを空にする', () => {
    for (let i = 1; i <= 12; i++) recordPerfSample('op', i * 10, { i })
    const out = drainPerfSamples()
    expect(out.count).toBe(12)
    expect(out.top).toHaveLength(8)
    expect(out.top[0].ms).toBe(120)
    expect(out.top[7].ms).toBe(50)
    expect(out.total_ms).toBe(780)
    expect(drainPerfSamples()).toBeNull()
  })

  it('リング溢れ分は件数と合計 ms に集計され黙って消えない', () => {
    for (let i = 0; i < 70; i++) recordPerfSample('op', 10)
    const out = drainPerfSamples()
    expect(out.count).toBe(70)
    expect(out.total_ms).toBe(700)
  })

  it('sample なしの drain は null (= beacon が空 field を送らない)', () => {
    expect(drainPerfSamples()).toBeNull()
  })

  it('meta が sample にそのまま乗る', () => {
    recordPerfSample('md-render', 42.34, { len: 1000, streaming: true })
    const [s] = drainPerfSamples().top
    expect(s).toEqual({ name: 'md-render', ms: 42.3, len: 1000, streaming: true })
  })

  it('context は登録した getter を毎回評価し、 解除で null に戻る', () => {
    let n = 0
    const unregister = registerPerfContext(() => ({ msgs: ++n }))
    expect(readPerfContext()).toEqual({ msgs: 1 })
    expect(readPerfContext()).toEqual({ msgs: 2 })
    unregister()
    expect(readPerfContext()).toBeNull()
  })

  it('getter が throw しても beacon 側を壊さない (= null に倒す)', () => {
    registerPerfContext(() => { throw new Error('boom') })
    expect(readPerfContext()).toBeNull()
  })
})
