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
