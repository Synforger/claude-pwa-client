import { describe, it, expect } from 'vitest'
import { applyOverviewSnapshot, WANT_BUSY_TIMEOUT_MS } from './applyOverviewSnapshot.js'

function refOf(obj = {}) {
  return { current: obj }
}

describe('applyOverviewSnapshot — single authority for the stop button', () => {
  it('no optimistic: busy maps straight to loading', () => {
    const ref = refOf()
    expect(applyOverviewSnapshot({}, { s1: { busy: true } }, ref)).toEqual({ s1: true })
    expect(applyOverviewSnapshot({ s1: true }, { s1: { busy: false } }, ref)).toEqual({ s1: false })
  })

  it('core case: after the reply arrives, a busy=false snapshot always converges to loading=false (recovers dropped results)', () => {
    const ref = refOf()
    const next = applyOverviewSnapshot({ s1: true }, { s1: { busy: false } }, ref)
    expect(next.s1).toBe(false)
  })

  it('returns the same reference when nothing changed (no wasted re-renders)', () => {
    const ref = refOf()
    const prev = { s1: true }
    expect(applyOverviewSnapshot(prev, { s1: { busy: true } }, ref)).toBe(prev)
  })

  // --- 送信 (want:'busy') ---
  it('send: observing busy=true confirms the turn started and clears the flag', () => {
    const ref = refOf({ s1: { want: 'busy', startedAt: 1000 } })
    const next = applyOverviewSnapshot({ s1: true }, { s1: { busy: true } }, ref, 1500)
    expect(next.s1 ?? true).toBe(true)
    expect(ref.current.s1).toBe(null)
  })

  it('send: during startup lag (within 10s) consecutive busy=false snapshots keep the stop button', () => {
    // 旧仕様は「busy=false が 2 連続で諦め」 → 立ち上がり race で送信ボタン解禁の jank
    // (= 「推論中なのに送信できる」)。 新仕様は時間ベースで、 startedAt から 10s 以内は
    // 何回 busy=false が来ても保持する (= 通常の立ち上がりは確実に猶予内に busy=true)。
    const ref = refOf({ s1: { want: 'busy', startedAt: 1000 } })
    let next = applyOverviewSnapshot({ s1: true }, { s1: { busy: false } }, ref, 1500)
    expect(next.s1).toBe(true)
    next = applyOverviewSnapshot(next, { s1: { busy: false } }, ref, 2000)
    expect(next.s1).toBe(true)               // 2 回目も保持 (= 旧仕様の誤諦めバグ根治)
    next = applyOverviewSnapshot(next, { s1: { busy: false } }, ref, 5000)
    expect(next.s1).toBe(true)               // 3 回目以降も保持
    expect(ref.current.s1).toEqual({ want: 'busy', startedAt: 1000 })  // 解除されない
  })

  it('send: only after the 10s timeout does it give up and return to the send button', () => {
    // 立ち上がり 10s 経っても backend busy=true が観測できない = no-op turn か PTY 経路の異常。
    // ここでようやく諦めて権威に従う (= 送信ボタンに戻す)。 停止ボタンが空打ちにならない上限。
    const ref = refOf({ s1: { want: 'busy', startedAt: 1000 } })
    const next = applyOverviewSnapshot({ s1: true }, { s1: { busy: false } }, ref, 1000 + WANT_BUSY_TIMEOUT_MS + 1)
    expect(next.s1).toBe(false)
    expect(ref.current.s1).toBe(null)
  })

  // --- 停止 (want:'idle') = 旧来の根治を維持 ---
  it('stop: one press switches to send — a stale busy=true snapshot right after does not flip it back', () => {
    const ref = refOf({ s1: { want: 'idle', startedAt: 1000 } })
    let next = applyOverviewSnapshot({ s1: false }, { s1: { busy: true } }, ref, 1100)
    expect(next.s1).toBe(false)
    expect(ref.current.s1).toEqual({ want: 'idle', startedAt: 1000 })
    next = applyOverviewSnapshot(next, { s1: { busy: false } }, ref, 1200)
    expect(next.s1).toBe(false)
    expect(ref.current.s1).toBe(null)
  })

  it('stop: an immediate busy=false observation settles and clears on the spot', () => {
    const ref = refOf({ s1: { want: 'idle', startedAt: 1000 } })
    const next = applyOverviewSnapshot({ s1: false }, { s1: { busy: false } }, ref, 1100)
    expect(next.s1).toBe(false)
    expect(ref.current.s1).toBe(null)
  })

  it('stop: no timeout — holds through any number of busy=true snapshots until the backend returns user_stopped -> busy=false', () => {
    const ref = refOf({ s1: { want: 'idle', startedAt: 1000 } })
    // 30 秒経過しても保持 (= 停止意図には WANT_BUSY_TIMEOUT_MS を適用しない)
    let next = applyOverviewSnapshot({ s1: false }, { s1: { busy: true } }, ref, 1000 + 30000)
    expect(next.s1).toBe(false)
    next = applyOverviewSnapshot(next, { s1: { busy: true } }, ref, 1000 + 60000)
    expect(next.s1).toBe(false)
    expect(ref.current.s1).toEqual({ want: 'idle', startedAt: 1000 })
    next = applyOverviewSnapshot(next, { s1: { busy: false } }, ref, 1000 + 60001)
    expect(next.s1).toBe(false)
    expect(ref.current.s1).toBe(null)
  })

  it('applies one snapshot to multiple sessions independently', () => {
    const ref = refOf()
    const next = applyOverviewSnapshot(
      { a: true, b: false },
      { a: { busy: false }, b: { busy: true } },
      ref,
    )
    expect(next).toEqual({ a: false, b: true })
  })
})
