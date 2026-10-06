// 拡張の到達判定 (= 宣言のうち HEAD が通った物だけを宣言順で残す) の検査。
import { describe, it, expect } from 'vitest'
import { isPageOpen, resolveReachable } from './useExtensions.js'

const ext = (id) => ({ id, title: id, icon: '🧩', path: `/ext/${id}/` })

describe('features/extensions — resolveReachable', () => {
  it('keeps only reachable extensions, in declared order', async () => {
    const up = new Set(['/ext/c/', '/ext/a/'])
    const out = await resolveReachable([ext('a'), ext('b'), ext('c')], async (p) => up.has(p))
    expect(out.map((e) => e.id)).toEqual(['a', 'c'])
  })

  it('treats a throwing probe as unreachable without dropping the rest', async () => {
    const out = await resolveReachable([ext('a'), ext('b')], async (p) => {
      if (p === '/ext/a/') throw new Error('network')
      return true
    })
    expect(out.map((e) => e.id)).toEqual(['b'])
  })

  it('returns nothing for a missing or malformed declaration', async () => {
    expect(await resolveReachable(undefined, async () => true)).toEqual([])
    expect(await resolveReachable({ id: 'a' }, async () => true)).toEqual([])
  })
})

describe('features/extensions — isPageOpen', () => {
  const list = [{ ...ext('band'), view: 'band' }, { ...ext('reader'), view: 'page' }, ext('old')]

  it('is true only while the open extension is one declared as a page', () => {
    expect(isPageOpen(list, 'reader')).toBe(true)
    expect(isPageOpen(list, 'band')).toBe(false)
    expect(isPageOpen(list, null)).toBe(false)
  })

  it('takes an extension with no view (an older backend) as a band', () => {
    expect(isPageOpen(list, 'old')).toBe(false)
  })

  it('is false for an id that is not in the list (declared but unreachable)', () => {
    expect(isPageOpen(list, 'gone')).toBe(false)
    expect(isPageOpen([], 'reader')).toBe(false)
  })
})
