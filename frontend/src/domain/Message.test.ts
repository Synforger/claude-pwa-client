// domain/Message.ts (= 純粋 message model) の契約 test。
import { describe, it, expect } from 'vitest'
import {
  isUserMessage,
  isAgentMessage,
  isSystemMessage,
  isPersistableMessage,
  dedupKey,
  attachToolResults,
} from './Message.ts'

describe('role 判別', () => {
  it('user / agent / system を判別する', () => {
    expect(isUserMessage({ role: 'user', uuid: 'u', text: '' } as any)).toBe(true)
    expect(isAgentMessage({ role: 'agent', uuid: 'a', text: '', tools: [] } as any)).toBe(true)
    expect(isSystemMessage({ role: 'system', uuid: null, kind: 'task' } as any)).toBe(true)
    expect(isUserMessage({ role: 'agent' } as any)).toBe(false)
  })
})

describe('isPersistableMessage', () => {
  it('uuid 確定済みのみ persist 可', () => {
    expect(isPersistableMessage({ role: 'user', uuid: 'u1', text: 'x' } as any)).toBe(true)
    expect(isPersistableMessage({ role: 'user', uuid: '', text: 'x' } as any)).toBe(false)
  })

  it('uuid undefined の system banner で TypeError を起こさない (= J-16 回帰)', () => {
    // 旧実装は `m.uuid !== null && m.uuid.length` で undefined.length を評価して墜ちた
    expect(isPersistableMessage({ role: 'system', kind: 'task' } as any)).toBe(false)
    expect(isPersistableMessage({ role: 'system', uuid: null, kind: 'task' } as any)).toBe(false)
  })
})

describe('dedupKey', () => {
  it('sid + role + uuid で一意 key を作る (= uuid null は空文字)', () => {
    expect(dedupKey('s1', { role: 'user', uuid: 'u1' } as any)).toBe('s1|user|u1')
    expect(dedupKey('s1', { role: 'system', uuid: null } as any)).toBe('s1|system|')
  })
})

describe('attachToolResults', () => {
  const tools = [
    { id: 't1', name: 'Bash' },
    { id: 't2', name: 'Read' },
  ] as any

  it('tool_use_id 一致の tool に result を付け、 changed=true を返す', () => {
    const { tools: next, changed } = attachToolResults(tools, [
      { tool_use_id: 't2', content: 'out', is_error: false } as any,
    ])
    expect(changed).toBe(true)
    expect(next[1].result).toEqual({ content: 'out', is_error: false })
    expect(next[0]).toBe(tools[0])  // 触ってない tool は参照維持
  })

  it('一致なしは同一配列参照 + changed=false (= 無駄 re-render 防止)', () => {
    const { tools: next, changed } = attachToolResults(tools, [
      { tool_use_id: 'nope', content: 'x' } as any,
    ])
    expect(changed).toBe(false)
    expect(next).toBe(tools)
  })

  it('results 空は即 no-op', () => {
    const { tools: next, changed } = attachToolResults(tools, [])
    expect(changed).toBe(false)
    expect(next).toBe(tools)
  })

  it('is_error は truthy 正規化される', () => {
    const { tools: next } = attachToolResults(tools, [
      { tool_use_id: 't1', content: 'err', is_error: 1 } as any,
    ])
    expect(next[0].result.is_error).toBe(true)
  })
})
