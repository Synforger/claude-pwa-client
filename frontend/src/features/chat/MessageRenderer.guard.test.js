import { describe, it, expect } from 'vitest'
import { isOversizedMessage, MARKDOWN_MAX_CHARS } from './MessageRenderer.jsx'

describe('isOversizedMessage', () => {
  it('a normal long reply renders as markdown (not oversized)', () => {
    expect(isOversizedMessage('ふつうの回答'.repeat(100))).toBe(false)
    expect(isOversizedMessage('a'.repeat(MARKDOWN_MAX_CHARS))).toBe(false)
  })

  it('over the threshold falls back to plain text', () => {
    expect(isOversizedMessage('a'.repeat(MARKDOWN_MAX_CHARS + 1))).toBe(true)
  })

  it('catches output degeneration (the same token repeated tens of thousands of times)', () => {
    // 実際に観測した 224KB の "court" 反復メッセージ相当。
    const degenerate = 'court\n\n'.repeat(32000)
    expect(degenerate.length).toBeGreaterThan(200_000)
    expect(isOversizedMessage(degenerate)).toBe(true)
  })

  it('non-strings and empties are false', () => {
    expect(isOversizedMessage('')).toBe(false)
    expect(isOversizedMessage(null)).toBe(false)
    expect(isOversizedMessage(undefined)).toBe(false)
  })
})
