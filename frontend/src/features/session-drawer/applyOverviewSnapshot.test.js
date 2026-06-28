import { describe, it, expect } from 'vitest'
import { applyOverviewSnapshot, WANT_BUSY_TIMEOUT_MS } from './applyOverviewSnapshot.js'

function refOf(obj = {}) {
  return { current: obj }
}

describe('applyOverviewSnapshot — 停止ボタンの単一権威', () => {
  it('optimistic なし: busy をそのまま loading に反映', () => {
    const ref = refOf()
    expect(applyOverviewSnapshot({}, { s1: { busy: true } }, ref)).toEqual({ s1: true })
    expect(applyOverviewSnapshot({ s1: true }, { s1: { busy: false } }, ref)).toEqual({ s1: false })
  })

  it('★本丸: 返信到達後 busy=false の snapshot で必ず loading=false に収束 (result 取りこぼし回復)', () => {
    const ref = refOf()
    const next = applyOverviewSnapshot({ s1: true }, { s1: { busy: false } }, ref)
    expect(next.s1).toBe(false)
  })

  it('変化が無ければ同一参照を返す (= 無駄な再 render を起こさない)', () => {
    const ref = refOf()
    const prev = { s1: true }
    expect(applyOverviewSnapshot(prev, { s1: { busy: true } }, ref)).toBe(prev)
  })

  // --- 送信 (want:'busy') ---
  it('送信: busy=true 観測でターン開始確認、 フラグ解除', () => {
    const ref = refOf({ s1: { want: 'busy', startedAt: 1000 } })
    const next = applyOverviewSnapshot({ s1: true }, { s1: { busy: true } }, ref, 1500)
    expect(next.s1 ?? true).toBe(true)
    expect(ref.current.s1).toBe(null)
  })

  it('★送信: 立ち上がり遅延中 (= 10s 以内) は busy=false の連続 snapshot でも停止ボタン保持', () => {
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

  it('★送信: タイムアウト (10s 超) でやっと諦めて送信ボタンへ', () => {
    // 立ち上がり 10s 経っても backend busy=true が観測できない = no-op turn か PTY 経路の異常。
    // ここでようやく諦めて権威に従う (= 送信ボタンに戻す)。 停止ボタンが空打ちにならない上限。
    const ref = refOf({ s1: { want: 'busy', startedAt: 1000 } })
    const next = applyOverviewSnapshot({ s1: true }, { s1: { busy: false } }, ref, 1000 + WANT_BUSY_TIMEOUT_MS + 1)
    expect(next.s1).toBe(false)
    expect(ref.current.s1).toBe(null)
  })

  // --- 停止 (want:'idle') = 旧来の根治を維持 ---
  it('★停止: 1 押下で送信へ — 直後の古い busy=true snapshot で停止に戻らない', () => {
    const ref = refOf({ s1: { want: 'idle', startedAt: 1000 } })
    let next = applyOverviewSnapshot({ s1: false }, { s1: { busy: true } }, ref, 1100)
    expect(next.s1).toBe(false)
    expect(ref.current.s1).toEqual({ want: 'idle', startedAt: 1000 })
    next = applyOverviewSnapshot(next, { s1: { busy: false } }, ref, 1200)
    expect(next.s1).toBe(false)
    expect(ref.current.s1).toBe(null)
  })

  it('停止: busy=false を即観測したらその場で確定・解除', () => {
    const ref = refOf({ s1: { want: 'idle', startedAt: 1000 } })
    const next = applyOverviewSnapshot({ s1: false }, { s1: { busy: false } }, ref, 1100)
    expect(next.s1).toBe(false)
    expect(ref.current.s1).toBe(null)
  })

  it('★停止: タイムアウト無し — backend が user_stopped→busy=false を返すまで何 snapshot busy=true でも保持', () => {
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
