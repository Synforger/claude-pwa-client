import { describe, it, expect } from 'vitest'
import { applyOverviewSnapshot } from './applyOverviewSnapshot.js'

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
    const ref = refOf({ s1: { want: 'busy', seen: false } })
    const next = applyOverviewSnapshot({ s1: true }, { s1: { busy: true } }, ref)
    expect(next.s1 ?? true).toBe(true)
    expect(ref.current.s1).toBe(null)
  })

  it('送信: busy=false は 1 回保留 (停止維持)、 2 回目で送信ボタンへ', () => {
    const ref = refOf({ s1: { want: 'busy', seen: false } })
    let next = applyOverviewSnapshot({ s1: true }, { s1: { busy: false } }, ref)
    expect(next.s1).toBe(true)               // 1 回目: 停止のまま保留
    expect(ref.current.s1).toEqual({ want: 'busy', seen: true })
    next = applyOverviewSnapshot(next, { s1: { busy: false } }, ref)
    expect(next.s1).toBe(false)              // 2 回目: 送信へ
    expect(ref.current.s1).toBe(null)
  })

  // --- 停止 (want:'idle') = 今回の修正対象 ---
  it('★停止: 1 押下で送信へ — 直後の古い busy=true snapshot で停止に戻らない', () => {
    const ref = refOf({ s1: { want: 'idle', seen: false } })
    // 停止直後、 backend 未処理の古い busy=true snapshot が来ても loading=false を保持
    let next = applyOverviewSnapshot({ s1: false }, { s1: { busy: true } }, ref)
    expect(next.s1).toBe(false)              // 送信ボタンのまま (= 停止に戻らない)
    expect(ref.current.s1).toEqual({ want: 'idle', seen: true })
    // backend が user_stopped→busy=false を返したら確定、 解除
    next = applyOverviewSnapshot(next, { s1: { busy: false } }, ref)
    expect(next.s1).toBe(false)
    expect(ref.current.s1).toBe(null)
  })

  it('停止: busy=false を即観測したらその場で確定・解除', () => {
    const ref = refOf({ s1: { want: 'idle', seen: false } })
    const next = applyOverviewSnapshot({ s1: false }, { s1: { busy: false } }, ref)
    expect(next.s1).toBe(false)
    expect(ref.current.s1).toBe(null)
  })

  it('★停止: ストリーム中で busy=true が何回続いても諦めず送信ボタンを保持 (= 2 押し不要)', () => {
    // 停止押下時に返信がまだ流れてる (= busy=true) ケース。 backend が user_stopped→busy=false
    // を返すまで、 何 snapshot busy=true が来ても loading=false を保持し続ける。
    const ref = refOf({ s1: { want: 'idle', seen: false } })
    let next = applyOverviewSnapshot({ s1: false }, { s1: { busy: true } }, ref)
    expect(next.s1).toBe(false)              // 1 回目保留
    next = applyOverviewSnapshot(next, { s1: { busy: true } }, ref)
    expect(next.s1).toBe(false)              // 2 回目も保持 (= 停止に戻らない)
    next = applyOverviewSnapshot(next, { s1: { busy: true } }, ref)
    expect(next.s1).toBe(false)              // 3 回目も保持
    expect(ref.current.s1).toEqual({ want: 'idle', seen: true })
    // backend が停止を処理 (busy=false) → 確定・解除
    next = applyOverviewSnapshot(next, { s1: { busy: false } }, ref)
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
