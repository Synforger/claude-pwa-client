// @vitest-environment jsdom
//
// bumpAllSubscribedSse (= foreground 復帰時の SSE 一括張り直し) の契約 test。
//
// iOS が bg で silent-dead にした SSE を復帰時に確実に張り直す + subscriber ゼロの
// instance は起こさない、 を固定する (= 📋 tasks / model / ctx 凍結の根治)。
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { createSseSubscriber, bumpAllSubscribedSse } from './_sse.ts'

class FakeEventSource {
  static instances = []
  constructor(url) {
    this.url = url
    this.readyState = 1
    this.closed = false
    FakeEventSource.instances.push(this)
  }
  close() { this.closed = true }
}

beforeEach(() => {
  FakeEventSource.instances = []
  vi.stubGlobal('EventSource', FakeEventSource)
})

describe('bumpAllSubscribedSse', () => {
  it('subscriber の居る singleton は close → 新規接続で張り直す', () => {
    const sse = createSseSubscriber({ name: `t-active-${Date.now()}`, path: '/x/stream' })
    const unsub = sse.subscribe(() => {})
    expect(FakeEventSource.instances).toHaveLength(1)
    bumpAllSubscribedSse()
    expect(FakeEventSource.instances).toHaveLength(2)   // 張り直しで新規接続
    expect(FakeEventSource.instances[0].closed).toBe(true)  // 旧接続は close 済
    unsub()
  })

  it('subscriber ゼロの singleton は起こさない', () => {
    createSseSubscriber({ name: `t-idle-${Date.now()}`, path: '/y/stream' })
    const before = FakeEventSource.instances.length
    bumpAllSubscribedSse()
    expect(FakeEventSource.instances).toHaveLength(before)  // 新規接続なし
  })
})

describe('生存監視 (= heartbeat + liveness watchdog)', () => {
  it('heartbeat frame は handler に流れず、 受信時刻だけ更新される', () => {
    vi.useFakeTimers()
    const sse = createSseSubscriber({ name: `t-hb-${Math.random()}`, path: '/hb/stream' })
    const seen = []
    const unsub = sse.subscribe(d => seen.push(d))
    const es = FakeEventSource.instances.at(-1)
    es.onmessage({ data: '{"_hb":1}' })
    es.onmessage({ data: '{"real":"payload"}' })
    expect(seen).toEqual([{ real: 'payload' }])
    unsub()
    vi.useRealTimers()
  })

  it('可視 + データ 65s 途絶で自動張り直し、 heartbeat が届いていれば張り直さない', () => {
    vi.useFakeTimers()
    const sse = createSseSubscriber({ name: `t-live-${Math.random()}`, path: '/live/stream' })
    const unsub = sse.subscribe(() => {})
    const first = FakeEventSource.instances.length
    // heartbeat が 60s ごとに届く限り張り直しなし
    for (let i = 0; i < 3; i++) {
      vi.advanceTimersByTime(60_000)
      FakeEventSource.instances.at(-1).onmessage({ data: '{"_hb":1}' })
    }
    expect(FakeEventSource.instances).toHaveLength(first)
    // 途絶 (= 何も届かない) → 65s 超で bump
    vi.advanceTimersByTime(80_000)
    expect(FakeEventSource.instances.length).toBeGreaterThan(first)
    unsub()
    vi.useRealTimers()
  })
})

describe('遅参 subscriber への再配布 (= 📋 パネル no tasks 根治)', () => {
  it('接続確立後にマウントされた consumer は直近 payload を即時に受け取る', () => {
    const sse = createSseSubscriber({ name: `t-late-${Math.random()}`, path: '/late/stream' })
    const first = []
    const unsub1 = sse.subscribe(d => first.push(d))
    // 初期 snapshot は最初の subscriber だけが live で受ける (= サーバは接続時に 1 回)
    FakeEventSource.instances.at(-1).onmessage({ data: '{"ses_a":{"tasks":[{"id":"1"}]}}' })
    expect(first).toHaveLength(1)
    // ここで 📋 パネルが開く (= 遅参 subscribe) — 従来は次の push まで永遠に空だった
    const late = []
    const unsub2 = sse.subscribe(d => late.push(d))
    expect(late).toHaveLength(1)
    expect(late[0].ses_a.tasks).toHaveLength(1)
    unsub1(); unsub2()
  })

  it('heartbeat は lastData を汚さない (= 遅参者に {_hb} を配らない)', () => {
    const sse = createSseSubscriber({ name: `t-latehb-${Math.random()}`, path: '/latehb/stream' })
    const unsub1 = sse.subscribe(() => {})
    FakeEventSource.instances.at(-1).onmessage({ data: '{"real":1}' })
    FakeEventSource.instances.at(-1).onmessage({ data: '{"_hb":1}' })
    const late = []
    const unsub2 = sse.subscribe(d => late.push(d))
    expect(late).toEqual([{ real: 1 }])
    unsub1(); unsub2()
  })
})
