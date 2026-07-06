// @vitest-environment jsdom
//
// useStreamBuffer (= SSE 細切れ frame の rAF バッファ) の契約 test。
//
// 急所: flush 時の bubble マージ規則。 同 uuid の追加 frame が既存 bubble の tools を
// 消さない (= multi-frame の 2 個目で 1 個目が消えた過去 bug)、 空 streaming placeholder
// への埋め込み、 uuid 不一致時の新 bubble append。 rAF の実発火は待たず cancelAndFlush
// (= 同期 flush) で検証する。
import { describe, it, expect } from 'vitest'
import { renderHook } from '@testing-library/react'
import { useStreamBuffer } from './useStreamBuffer.js'

function host(initial = {}) {
  let state = initial
  const setMessages = (fn) => { state = fn(state) }
  const { result } = renderHook(() => useStreamBuffer({ setMessages }))
  return { hook: result.current, get: () => state }
}

function fill(buf, { text = null, thinking = null, tools = [], uuid = null }) {
  buf.text = text
  buf.thinking = thinking
  buf.newTools = tools
  buf.uuid = uuid
  buf.needsNewBubble = true
  buf.dirty = true
}

describe('useStreamBuffer flush 契約', () => {
  it('dirty でない buf の flush は no-op', () => {
    const { hook, get } = host({ s1: [] })
    hook.cancelAndFlush('s1')
    expect(get().s1).toHaveLength(0)
  })

  it('新規 bubble append: uuid 付き streaming agent が積まれる', () => {
    const { hook, get } = host({ s1: [] })
    fill(hook.bufFor('s1'), { text: 'こんにちは', uuid: 'AM1' })
    hook.cancelAndFlush('s1')
    const last = get().s1.at(-1)
    expect(last.role).toBe('agent')
    expect(last.uuid).toBe('AM1')
    expect(last.text).toBe('こんにちは')
    expect(last.streaming).toBe(true)
  })

  it('同 uuid の追加 frame は既存 bubble にマージし、 既存 tools を消さない', () => {
    const { hook, get } = host({
      s1: [{ id: 'a', role: 'agent', uuid: 'AM1', text: 'v1',
             tools: [{ id: 't1', name: 'Bash' }], streaming: true }],
    })
    fill(hook.bufFor('s1'), { text: 'v2', tools: [{ id: 't2', name: 'Read' }], uuid: 'AM1' })
    hook.cancelAndFlush('s1')
    const bubble = get().s1[0]
    expect(bubble.text).toBe('v2')
    expect(bubble.tools.map(t => t.id)).toEqual(['t1', 't2'])
  })

  it('同 uuid frame の空 text は既存 text を上書きしない (= tool_use 行で本文が消えない)', () => {
    const { hook, get } = host({
      s1: [{ id: 'a', role: 'agent', uuid: 'AM1', text: '本文', tools: [], streaming: true }],
    })
    fill(hook.bufFor('s1'), { text: null, tools: [{ id: 't1', name: 'Bash' }], uuid: 'AM1' })
    hook.cancelAndFlush('s1')
    expect(get().s1[0].text).toBe('本文')
    expect(get().s1[0].tools).toHaveLength(1)
  })

  it('送信直後の空 streaming placeholder には新 bubble を作らず埋める', () => {
    const { hook, get } = host({
      s1: [{ id: 'ph', role: 'agent', text: '', thinking: null, tools: [], streaming: true }],
    })
    fill(hook.bufFor('s1'), { text: '応答', uuid: 'AM2' })
    hook.cancelAndFlush('s1')
    const arr = get().s1
    expect(arr).toHaveLength(1)
    expect(arr[0].id).toBe('ph')
    expect(arr[0].text).toBe('応答')
    expect(arr[0].uuid).toBe('AM2')
  })

  it('historical uuid (= 末尾窓の外) でも全長走査で既存 bubble に dedup される', () => {
    const old = { id: 'old', role: 'agent', uuid: 'AM-old', text: '過去', tools: [], streaming: false }
    const fillers = Array.from({ length: 50 }, (_, i) => ({ id: `f${i}`, role: 'user', text: String(i) }))
    const { hook, get } = host({ s1: [old, ...fillers] })
    fill(hook.bufFor('s1'), { text: '過去', uuid: 'AM-old' })
    hook.cancelAndFlush('s1')
    expect(get().s1).toHaveLength(51)  // 重複 append しない
  })

  it('resetBuf で buf が初期化される', () => {
    const { hook } = host()
    const buf = hook.bufFor('s1')
    fill(buf, { text: 'x', uuid: 'AM1' })
    hook.resetBuf('s1')
    expect(hook.bufFor('s1').dirty).toBe(false)
    expect(hook.bufFor('s1').text).toBe(null)
  })
})
