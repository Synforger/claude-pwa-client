// classifyTaskNotification / iconForTaskType の pure test。 実 harness 実行時の
// summary サンプルで型判別が命中するかを担保。
import { describe, it, expect } from 'vitest'
import { classifyTaskNotification, iconForTaskType } from './classifyTaskNotification.js'

describe('classifyTaskNotification', () => {
  it('detects agent from Agent "..." finished summary', () => {
    expect(classifyTaskNotification('Agent "Obsidian RAG OSS 調査" finished')).toBe('agent')
    expect(classifyTaskNotification('Agent "Search angle 1" finished')).toBe('agent')
  })

  it('detects bash from Background command "..." completed', () => {
    expect(classifyTaskNotification('Background command "brew install bash background" completed (exit code 0)')).toBe('bash')
    expect(classifyTaskNotification('Background command "docs-check" completed (exit code 1)')).toBe('bash')
  })

  it('detects monitor from Monitor event: "..."', () => {
    expect(classifyTaskNotification('Monitor event: "remaining 4 search agents completion"')).toBe('monitor')
  })

  it('detects monitor from Monitor "..." stream ended (= 終了通知の第 2 形式)', () => {
    expect(classifyTaskNotification('Monitor "az003_v5 progress" stream ended')).toBe('monitor')
    expect(classifyTaskNotification('Monitor \\"escaped quotes\\" stream ended')).toBe('monitor')
  })

  it('falls back to unknown for missing / unrecognized summary', () => {
    expect(classifyTaskNotification(null)).toBe('unknown')
    expect(classifyTaskNotification(undefined)).toBe('unknown')
    expect(classifyTaskNotification('')).toBe('unknown')
    expect(classifyTaskNotification('random text that does not match')).toBe('unknown')
  })

  it('does not match Agent-like text mid-string (schema is prefix-only)', () => {
    // 「本文中に "Agent \"" が偶然登場」 しても命中しない
    expect(classifyTaskNotification('mentions Agent "foo" somewhere')).toBe('unknown')
  })

  it('iconForTaskType maps each type to a distinct glyph', () => {
    expect(iconForTaskType('agent')).toBe('🤖')
    expect(iconForTaskType('bash')).toBe('⚙')
    expect(iconForTaskType('monitor')).toBe('👁')
    expect(iconForTaskType('unknown')).toBe('⚙')
  })
})
