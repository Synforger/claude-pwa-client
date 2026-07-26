import { describe, it, expect } from 'vitest'
import { displayWindowStart } from './ChatPanel.jsx'
import { sortByTs } from '../features/chat/sortByTs.js'

// 中抜け根治 (= 2026-07-27)。
// messages 配列は「cache 復元 (= 直近の会話) が先頭 → GET 履歴取り込みで古い行が末尾」 という
// 時系列と食い違う並びになる。 表示 window を配列位置で切ると新しい cache 分が窓外に落ちる。
describe('表示 window は時系列で切る', () => {
  const LIMIT = 100
  // 実機の形を再現: 直近 30 件 (cache) が先頭、 その後に古い 110 件 (GET replay) が append
  const recentFromCache = Array.from({ length: 30 }, (_, i) => ({
    id: `recent-${i}`, role: 'user', text: `最近の発話${i}`, ts: 2_000_000_000_000 + i * 1000,
  }))
  const ancientFromGet = Array.from({ length: 110 }, (_, i) => ({
    id: `ancient-${i}`, role: 'agent', text: `大昔${i}`, ts: 1_000_000_000_000 + i * 1000,
  }))
  const state = [...recentFromCache, ...ancientFromGet]  // 計 140 件

  it('配列位置で切ると最近のメッセージが消える (= 修正前の挙動を明示)', () => {
    const start = displayWindowStart(state.length, null, LIMIT)
    const shown = state.slice(start)
    const shownRecent = shown.filter(m => m.id.startsWith('recent-')).length
    expect(shownRecent).toBe(0)  // 直近 30 件が全部消える = 中抜け
  })

  it('時系列に並べてから切れば最近のメッセージが必ず残る (= 修正後)', () => {
    const ordered = sortByTs(state)
    const start = displayWindowStart(ordered.length, null, LIMIT)
    const shown = ordered.slice(start)
    // 直近 30 件は 1 件も落ちない
    expect(shown.filter(m => m.id.startsWith('recent-'))).toHaveLength(30)
    // 表示は時系列末尾 = 最新が最後に来る
    expect(shown[shown.length - 1].id).toBe('recent-29')
    expect(shown).toHaveLength(LIMIT)
  })

  it('溢れる時に落ちるのは常に最古のものだけ (= 中抜けしない)', () => {
    const ordered = sortByTs(state)
    const shown = ordered.slice(displayWindowStart(ordered.length, null, LIMIT))
    const dropped = ordered.slice(0, displayWindowStart(ordered.length, null, LIMIT))
    const newestDropped = Math.max(...dropped.map(m => m.ts))
    const oldestShown = Math.min(...shown.map(m => m.ts))
    expect(newestDropped).toBeLessThan(oldestShown)  // 境界より新しいものは必ず表示される
  })
})
