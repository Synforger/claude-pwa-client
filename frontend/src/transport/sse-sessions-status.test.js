// @vitest-environment jsdom
//
// sessions-status の localStorage write-through + hydrate (= 「上部バー --- のまま」 根治)。
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { sessionsStatusSse, getCachedAllStatus } from './sse-sessions-status.ts'

class FakeEventSource {
  static instances = []
  constructor(url) { this.url = url; FakeEventSource.instances.push(this) }
  close() {}
}

// jsdom 環境で localStorage が未定義になる構成があるため in-memory mock を明示 stub する。
function makeStorage() {
  const m = new Map()
  return {
    getItem: k => (m.has(k) ? m.get(k) : null),
    setItem: (k, v) => m.set(k, String(v)),
    removeItem: k => m.delete(k),
    clear: () => m.clear(),
  }
}

beforeEach(() => {
  FakeEventSource.instances = []
  vi.stubGlobal('EventSource', FakeEventSource)
  vi.stubGlobal('localStorage', makeStorage())
})

describe('sessions-status cache', () => {
  it('payload 受信で localStorage に write-through され、 hydrate で読める', () => {
    const unsub = sessionsStatusSse.subscribe(() => {})
    FakeEventSource.instances.at(-1).onmessage({
      data: '{"ses_x":{"model":"Fable 5","five_hour_pct":40}}',
    })
    unsub()
    const cached = getCachedAllStatus()
    expect(cached.ses_x.model).toBe('Fable 5')
    expect(cached.ses_x.five_hour_pct).toBe(40)
  })

  it('cache 不在 / 壊れた JSON は {} (= 真の初回起動だけ "---" 相当)', () => {
    expect(getCachedAllStatus()).toEqual({})
    localStorage.setItem('cpc_last_all_status', '{broken')
    expect(getCachedAllStatus()).toEqual({})
  })
})
