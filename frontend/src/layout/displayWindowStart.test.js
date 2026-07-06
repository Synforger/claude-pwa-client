// displayWindowStart (= 表示 window 先頭 index の導出) の契約 test。
//
// 要点: 過去閲覧中に凍結した frozenStart を使い続けることで、 新着で総数が
// DISPLAY_LIMIT を超えても「今読んでいる上方の DOM」 が slice から抜けない
// (= 表示位置が上にジャンプしない)。 底に居る時 (frozenStart=null) は従来通り
// 末尾 window。
import { describe, it, expect } from 'vitest'
import { displayWindowStart } from './ChatPanel.jsx'

describe('displayWindowStart', () => {
  it('凍結なし (= 底に居る) は末尾 window: max(0, len - limit)', () => {
    expect(displayWindowStart(50, null, 100)).toBe(0)
    expect(displayWindowStart(100, null, 100)).toBe(0)
    expect(displayWindowStart(150, null, 100)).toBe(50)
  })

  it('凍結中は新着で総数が増えても先頭が動かない (= window は末尾方向へだけ伸びる)', () => {
    // 150 件時点で過去閲覧開始 → 凍結 start = 50
    const frozen = displayWindowStart(150, null, 100)
    expect(frozen).toBe(50)
    // 新着 30 件: 通常なら start=80 だが凍結値 50 を維持 (= index 50-79 の DOM を守る)
    expect(displayWindowStart(180, frozen, 100)).toBe(50)
  })

  it('凍結値が末尾 window より後ろに来ることはない (= min で clamp)', () => {
    // 総数が減る方向 (= reconcile 置換等) でも window が空にならない
    expect(displayWindowStart(120, 50, 100)).toBe(20)
    expect(displayWindowStart(40, 50, 100)).toBe(0)
  })
})
