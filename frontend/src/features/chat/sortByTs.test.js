import { describe, it, expect } from 'vitest'
import { sortByTs } from './MessageList.jsx'

// 順序バグ根治: 表示は ts (epoch ms) で安定ソートし、 配列への入り方 (append 順) に依存せず
// 常に時系列で並ぶ。 ts 無しメッセージは直前の実効キーを継いで隣に留まる。

describe('sortByTs', () => {
  it('append 順がバラバラでも ts 昇順に並べ直す', () => {
    const scrambled = [
      { id: 'c', ts: 300 },
      { id: 'a', ts: 100 },
      { id: 'b', ts: 200 },
    ]
    expect(sortByTs(scrambled).map(m => m.id)).toEqual(['a', 'b', 'c'])
  })

  it('同 ts は元の相対順を維持する (stable)', () => {
    const same = [
      { id: 'x', ts: 100 },
      { id: 'y', ts: 100 },
      { id: 'z', ts: 100 },
    ]
    expect(sortByTs(same).map(m => m.id)).toEqual(['x', 'y', 'z'])
  })

  it('ts 無しメッセージは直前の ts を継いで時系列上の隣に留まる', () => {
    // user@100, (ts 無し system) , agent@200 → system は user と agent の間に留まる
    const msgs = [
      { id: 'agent', role: 'agent', ts: 200 },
      { id: 'user', role: 'user', ts: 100 },
      { id: 'sysmarker', role: 'system' }, // ts 無し、 配列上は user の後ろ (= 100 を継ぐ)
    ]
    // 元 index: agent=0, user=1, sysmarker=2。 sysmarker は carry=100 (user の後ろ) を継ぐ。
    // key: agent=200, user=100, sysmarker=100。 sort(key, index): user(100,1) < sysmarker(100,2) < agent(200,0)
    expect(sortByTs(msgs).map(m => m.id)).toEqual(['user', 'sysmarker', 'agent'])
  })

  it('末尾の楽観バブル (ts=最新) は最後に来る', () => {
    const msgs = [
      { id: 'old', ts: 100 },
      { id: 'mid', ts: 200 },
      { id: 'optimistic', ts: 999 }, // 送信直後 Date.now()
    ]
    expect(sortByTs(msgs).map(m => m.id)).toEqual(['old', 'mid', 'optimistic'])
  })

  it('空配列は空を返す / 全て ts 無しは元順維持', () => {
    expect(sortByTs([])).toEqual([])
    const noTs = [{ id: 'a' }, { id: 'b' }, { id: 'c' }]
    expect(sortByTs(noTs).map(m => m.id)).toEqual(['a', 'b', 'c'])
  })
})
