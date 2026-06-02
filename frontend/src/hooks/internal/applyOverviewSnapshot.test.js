import { describe, it, expect } from 'vitest'
import { applyOverviewSnapshot } from './applyOverviewSnapshot.js'

function refOf(obj = {}) {
  return { current: obj }
}

describe('applyOverviewSnapshot — 停止ボタンの単一権威', () => {
  it('pending なし: busy をそのまま loading に反映', () => {
    const ref = refOf()
    expect(applyOverviewSnapshot({}, { s1: { busy: true } }, ref)).toEqual({ s1: true })
    expect(applyOverviewSnapshot({ s1: true }, { s1: { busy: false } }, ref)).toEqual({ s1: false })
  })

  it('★本丸: 返信到達後 busy=false の snapshot で必ず loading=false に収束 (result 取りこぼし回復)', () => {
    // per-tab の result event を取りこぼして loading=true で居座っていても、
    // 次の overview snapshot (busy=false) が確定的に false へ落とす。
    const ref = refOf()
    const next = applyOverviewSnapshot({ s1: true }, { s1: { busy: false } }, ref)
    expect(next.s1).toBe(false)
  })

  it('変化が無ければ同一参照を返す (= 無駄な再 render を起こさない)', () => {
    const ref = refOf()
    const prev = { s1: true }
    expect(applyOverviewSnapshot(prev, { s1: { busy: true } }, ref)).toBe(prev)
  })

  it('pending + busy=true: ターン開始確認でフラグ解除、 loading=true', () => {
    const ref = refOf({ s1: { seen: false } })
    const next = applyOverviewSnapshot({ s1: true }, { s1: { busy: true } }, ref)
    expect(next.s1 ?? true).toBe(true)
    expect(ref.current.s1).toBe(null)
  })

  it('pending + busy=false: 1 回目は停止を保留、 2 回目で送信ボタンへ', () => {
    const ref = refOf({ s1: { seen: false } })
    // 1 回目: backend がまだ送信を処理してない猶予 → loading=true 維持、 seen=true
    let next = applyOverviewSnapshot({ s1: true }, { s1: { busy: false } }, ref)
    expect(next.s1).toBe(true)
    expect(ref.current.s1).toEqual({ seen: true })
    // 2 回目: ターンが立ち上がらなかった → loading=false、 フラグ解除
    next = applyOverviewSnapshot(next, { s1: { busy: false } }, ref)
    expect(next.s1).toBe(false)
    expect(ref.current.s1).toBe(null)
  })

  it('pending 中に busy=true が来たら即権威委譲 (= 通常のターン開始)', () => {
    const ref = refOf({ s1: { seen: false } })
    const next = applyOverviewSnapshot({ s1: true }, { s1: { busy: true } }, ref)
    expect(next.s1 ?? true).toBe(true)
    expect(ref.current.s1).toBe(null) // 以降は backend 権威
  })

  it('複数 session を 1 snapshot で個別に反映', () => {
    const ref = refOf()
    const next = applyOverviewSnapshot(
      { a: true, b: false },
      { a: { busy: false }, b: { busy: true } },
      ref,
    )
    expect(next).toEqual({ a: false, b: true })
  })
})
