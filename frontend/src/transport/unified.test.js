// @vitest-environment jsdom
//
// 統合 transport (= unified.ts) の unit test (= 2026-07-14 電力効率工事)。
//
// 担保する不変条件:
// 1. channel 振分 (= jsonl / status / overview / subagents) + 遅参 subscriber への
//    直近 payload 再配布 (= #184 と同規約)
// 2. jsonl frame の pos で offsets が前進し、 永続化は debounce + flush 経路
// 3. 購読 sid 差替 / view / stop が control POST になる + 404 で張り直し
// 4. 接続 URL に conn / jsonl (= sid:offset) / view が乗る
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'

class FakeEventSource {
  static instances = []
  constructor(url) {
    this.url = url
    this.readyState = 0
    FakeEventSource.instances.push(this)
  }
  close() { this.readyState = 2 }
  open() {
    this.readyState = 1
    this.onopen?.()
  }
  emit(obj) { this.onmessage?.({ data: JSON.stringify(obj) }) }
}
FakeEventSource.CONNECTING = 0
FakeEventSource.OPEN = 1
FakeEventSource.CLOSED = 2

function makeStorage() {
  const m = new Map()
  return {
    getItem: k => (m.has(k) ? m.get(k) : null),
    setItem: (k, v) => m.set(k, String(v)),
    removeItem: k => m.delete(k),
    clear: () => m.clear(),
  }
}

let apiCalls
vi.mock('./http.ts', () => ({
  httpClient: {
    apiFetch: (...args) => {
      const res = apiCalls.responder?.(...args) ?? { status: 200 }
      apiCalls.list.push(args)
      return Promise.resolve(res)
    },
  },
}))

// 各 test で fresh module を読み込む (= singleton の内部状態を隔離)
async function freshTransport() {
  vi.resetModules()
  return await import('./unified.ts')
}

beforeEach(() => {
  apiCalls = { list: [], responder: null }
  FakeEventSource.instances = []
  vi.stubGlobal('EventSource', FakeEventSource)
  vi.stubGlobal('localStorage', makeStorage())
  vi.useFakeTimers()
})

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('unified transport', () => {
  it('接続 URL に conn + 購読 sid:offset + view が乗る', async () => {
    localStorage.setItem('cpc_v2_jsonl_offsets', JSON.stringify({ ses_a: 123 }))
    const { unifiedTransport, unifiedJsonl } = await freshTransport()
    unifiedTransport.setActiveSid('ses_a')
    unifiedJsonl.setSubscribedSids(['ses_a'])
    const unsub = unifiedJsonl.subscribe(() => {})
    const es = FakeEventSource.instances.at(-1)
    expect(es.url).toContain('conn=')
    expect(decodeURIComponent(es.url)).toContain('jsonl=ses_a:123')
    expect(es.url).toContain('view=ses_a')
    unsub()
  })

  it('channel 振分: jsonl は handler + offsets 前進、 status は write-through', async () => {
    const { unifiedJsonl, unifiedStatusSse } = await freshTransport()
    const jsonlSeen = []
    const statusSeen = []
    const u1 = unifiedJsonl.subscribe(e => jsonlSeen.push(e))
    const u2 = unifiedStatusSse.subscribe(d => statusSeen.push(d))
    const es = FakeEventSource.instances.at(-1)
    es.open()
    es.emit({ ch: 'jsonl', pos: 777, ev: { type: 'assistant', sid: 'ses_a', uuid: 'x' } })
    es.emit({ ch: 'status', data: { ses_a: { model: 'Fable 5' } } })
    expect(jsonlSeen).toHaveLength(1)
    expect(jsonlSeen[0].uuid).toBe('x')
    expect(statusSeen.at(-1).ses_a.model).toBe('Fable 5')
    // offsets: debounce 前は未永続、 flush で書かれる
    vi.advanceTimersByTime(1100)
    expect(JSON.parse(localStorage.getItem('cpc_v2_jsonl_offsets')).ses_a).toBe(777)
    expect(JSON.parse(localStorage.getItem('cpc_last_all_status')).ses_a.model).toBe('Fable 5')
    u1(); u2()
  })

  it('遅参 subscriber に直近 payload を即再配布 (= #184 規約)', async () => {
    const { unifiedStatusSse, unifiedOverviewSse } = await freshTransport()
    const u1 = unifiedStatusSse.subscribe(() => {})
    const es = FakeEventSource.instances.at(-1)
    es.open()
    es.emit({ ch: 'status', data: { ses_a: { model: 'M' } } })
    es.emit({ ch: 'overview', data: { ses_a: { busy: true } } })
    const late = []
    const u2 = unifiedStatusSse.subscribe(d => late.push(d))
    const late2 = []
    const u3 = unifiedOverviewSse.subscribe(d => late2.push(d))
    expect(late).toHaveLength(1)
    expect(late[0].ses_a.model).toBe('M')
    expect(late2[0].ses_a.busy).toBe(true)
    u1(); u2(); u3()
  })

  it('購読差替 = control POST (= offsets 同梱)、 view / stop も POST', async () => {
    localStorage.setItem('cpc_v2_jsonl_offsets', JSON.stringify({ ses_b: 55 }))
    const { unifiedTransport, unifiedJsonl, unifiedViews } = await freshTransport()
    const unsub = unifiedJsonl.subscribe(() => {})
    const es = FakeEventSource.instances.at(-1)
    es.open()
    unifiedJsonl.setSubscribedSids(['ses_b'])
    unifiedViews.setActiveSid('ses_b')
    unifiedViews.sendStopIntent('ses_b')
    await vi.advanceTimersByTimeAsync(10)
    const bodies = apiCalls.list.map(([path, opts]) => ({ path, body: opts.jsonBody }))
    expect(bodies.some(b => b.body.op === 'jsonl' && b.body.sids[0].sid === 'ses_b' && b.body.sids[0].from === 55)).toBe(true)
    expect(bodies.some(b => b.body.op === 'view' && b.body.sid === 'ses_b')).toBe(true)
    expect(bodies.some(b => b.body.op === 'stop' && b.body.sid === 'ses_b')).toBe(true)
    expect(bodies.every(b => b.path.includes('/stream/unified/'))).toBe(true)
    void unifiedTransport
    unsub()
  })

  it('control 404 (= backend 再起動で conn 消失) で張り直す', async () => {
    const { unifiedJsonl, unifiedViews } = await freshTransport()
    const unsub = unifiedJsonl.subscribe(() => {})
    const es1 = FakeEventSource.instances.at(-1)
    es1.open()
    apiCalls.responder = () => ({ status: 404 })
    unifiedViews.setActiveSid('ses_a')
    await vi.advanceTimersByTimeAsync(10)
    // 旧 ES が閉じられ、 新しい ES が張られている
    expect(es1.readyState).toBe(2)
    expect(FakeEventSource.instances.length).toBeGreaterThan(1)
    unsub()
  })

  it('hello frame で desired state (= view / subagents) を再主張する', async () => {
    const { unifiedTransport, unifiedJsonl, unifiedSubagentsSse } = await freshTransport()
    unifiedTransport.setActiveSid('ses_a')
    const u1 = unifiedJsonl.subscribe(() => {})
    const u2 = unifiedSubagentsSse.subscribe('ses_a', () => {})
    const es = FakeEventSource.instances.at(-1)
    es.open()
    es.emit({ ch: 'sys', type: 'hello', conn: 'c' })
    await vi.advanceTimersByTimeAsync(10)
    const ops = apiCalls.list.map(([, opts]) => opts.jsonBody.op)
    expect(ops).toContain('view')
    expect(ops).toContain('subagents')
    u1(); u2()
  })

  it('subagents channel は sid 別に振分けられ、 遅参にも再配布', async () => {
    const { unifiedSubagentsSse, unifiedJsonl } = await freshTransport()
    const seen = []
    const keep = unifiedJsonl.subscribe(() => {})  // 接続維持用
    const u1 = unifiedSubagentsSse.subscribe('ses_a', d => seen.push(d))
    const es = FakeEventSource.instances.at(-1)
    es.open()
    es.emit({ ch: 'subagents', sid: 'ses_a', data: { subagents: [1] } })
    es.emit({ ch: 'subagents', sid: 'ses_other', data: { subagents: [9] } })
    expect(seen).toHaveLength(1)
    const late = []
    const u2 = unifiedSubagentsSse.subscribe('ses_a', d => late.push(d))
    expect(late[0].subagents).toEqual([1])
    u1(); u2(); keep()
  })
})
