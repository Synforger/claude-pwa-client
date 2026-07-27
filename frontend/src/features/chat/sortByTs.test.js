import { describe, it, expect } from 'vitest'
import { sortByTs } from './sortByTs.js'

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

  it('ts 無しメッセージは時系列上の隣に留まる (= 配列が時系列順の通常ケース)', () => {
    // user@100 → (ts 無し system) → agent@200 の順で積まれた通常の並び。
    // system は user と agent の間に留まる。
    const msgs = [
      { id: 'user', role: 'user', ts: 100 },
      { id: 'sysmarker', role: 'system' },  // ts 無し
      { id: 'agent', role: 'agent', ts: 200 },
    ]
    expect(sortByTs(msgs).map(m => m.id)).toEqual(['user', 'sysmarker', 'agent'])
  })

  it('配列順が時系列とズレていても、 ts 無しメッセージは過去に沈まない (= 2026-07-27 消失根治)', () => {
    // 履歴 replay 直後は「新しい message の後ろに古い message が append される」 状態になる。
    // ここで ts 無し bubble が直前要素の**生の** ts を継ぐと過去へ沈み、 表示窓 (= 末尾 N 件)
    // の外に落ちて画面から消える。 carry を「それまでに見た最大 ts」 にして構造的に防ぐ。
    const msgs = [
      { id: 'newest', role: 'agent', ts: 900 },
      { id: 'ancient', role: 'agent', ts: 100 },   // replay で後から積まれた古い行
      { id: 'noTs', role: 'user' },                 // ts を失った自分の発話
    ]
    // noTs は ancient(100) でなく、 それまでの最大 900 を継ぐ → 末尾に残る
    expect(sortByTs(msgs).map(m => m.id)).toEqual(['ancient', 'newest', 'noTs'])
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

  it('推論中 placeholder (ts 無し) は server ts へ確定した user の上に浮かない (= 2026-07-27 根治)', () => {
    // 送信 → user が server jsonl ts (= 端末刻印より必ず後ろ) で確定した直後、
    // placeholder がまだ実 frame を持たない window の再現。
    // 旧実装は placeholder に端末 Date.now() を刻んでいたため server ts に負けて
    // user の上に浮いた。 ts 無しなら carry (= 単調最大) が常に後ろへ置く。
    const confirmedUser = { id: 'u', role: 'user', ts: 5000 }       // server ts
    const placeholder = { id: 'ph', role: 'agent', streaming: true } // ts 無し
    expect(sortByTs([confirmedUser, placeholder]).map(m => m.id)).toEqual(['u', 'ph'])
    // 旧 bug の形 (= placeholder が古い端末 ts を持つ) は浮くことも固定しておく
    const stamped = { id: 'ph2', role: 'agent', streaming: true, ts: 4000 }
    expect(sortByTs([confirmedUser, stamped]).map(m => m.id)).toEqual(['ph2', 'u'])
  })
})
