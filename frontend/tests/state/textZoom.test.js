// state/textZoom.js (= メモとプレビューの字の大きさ) の契約 test。 値は端末に覚えるので、 保存場所は
// その場で作る物に向け、 読み込み直しは module を読み直して確かめる。
import { beforeEach, describe, expect, it, vi } from 'vitest'

function makeStorage() {
  const m = new Map()
  return {
    getItem: k => (m.has(k) ? m.get(k) : null),
    setItem: (k, v) => m.set(k, String(v)),
  }
}

async function load() {
  vi.resetModules()
  return import('../../src/state/textZoom.js')
}

describe('textZoom store', () => {
  beforeEach(() => { vi.stubGlobal('localStorage', makeStorage()) })

  it('keeps the size between the limits', async () => {
    const { TEXT_ZOOM_MAX, TEXT_ZOOM_MIN, clampTextZoom } = await load()
    expect(clampTextZoom(0.1)).toBe(TEXT_ZOOM_MIN)
    expect(clampTextZoom(1.3)).toBe(1.3)
    expect(clampTextZoom(9)).toBe(TEXT_ZOOM_MAX)
  })

  it('steps by 10%, from the nearest step when a pinch left it in between', async () => {
    const { TEXT_ZOOM_MAX, TEXT_ZOOM_MIN, stepTextZoom } = await load()
    expect(stepTextZoom(1, 1)).toBeCloseTo(1.1, 10)
    expect(stepTextZoom(1, -1)).toBeCloseTo(0.9, 10)
    expect(stepTextZoom(1.41, 1)).toBeCloseTo(1.5, 10)
    expect(stepTextZoom(1.41, -1)).toBeCloseTo(1.3, 10)
    expect(stepTextZoom(TEXT_ZOOM_MAX, 1)).toBe(TEXT_ZOOM_MAX)
    expect(stepTextZoom(TEXT_ZOOM_MIN, -1)).toBe(TEXT_ZOOM_MIN)
  })

  it('tells the subscribers, and is kept on the device', async () => {
    const first = await load()
    expect(first.getSnapshot().zoom).toBe(1)
    const seen = []
    first.subscribe(({ zoom }) => seen.push(zoom))
    first.setTextZoom(1.414)
    first.setTextZoom(1.414)
    expect(seen).toEqual([1.41])
    const again = await load()
    expect(again.getSnapshot().zoom).toBe(1.41)
  })

  it('starts at 100% when nothing usable is kept', async () => {
    localStorage.setItem('cpc_v2_text_zoom', 'big')
    expect((await load()).getSnapshot().zoom).toBe(1)
    localStorage.setItem('cpc_v2_text_zoom', '7')
    const { TEXT_ZOOM_MAX, getSnapshot } = await load()
    expect(getSnapshot().zoom).toBe(TEXT_ZOOM_MAX)
  })
})
