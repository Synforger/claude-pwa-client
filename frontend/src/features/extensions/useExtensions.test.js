// 拡張の到達判定 (= 宣言のうち HEAD が通った物だけを宣言順で残す) の検査。
import { describe, it, expect } from 'vitest'
import { resolveReachable } from './useExtensions.js'

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
