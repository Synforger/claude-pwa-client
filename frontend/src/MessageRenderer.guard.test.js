import { describe, it, expect } from 'vitest'
import { isOversizedMessage, MARKDOWN_MAX_CHARS } from './MessageRenderer.jsx'

describe('isOversizedMessage', () => {
  it('通常の長文回答は markdown 描画 (= 非 oversized)', () => {
    expect(isOversizedMessage('ふつうの回答'.repeat(100))).toBe(false)
    expect(isOversizedMessage('a'.repeat(MARKDOWN_MAX_CHARS))).toBe(false)
  })

  it('閾値超は plain text に倒す', () => {
    expect(isOversizedMessage('a'.repeat(MARKDOWN_MAX_CHARS + 1))).toBe(true)
  })

  it('出力 degeneration (= 同一語の数万回反復) を捕捉する', () => {
    // 実際に観測した 224KB の "court" 反復メッセージ相当。
    const degenerate = 'court\n\n'.repeat(32000)
    expect(degenerate.length).toBeGreaterThan(200_000)
    expect(isOversizedMessage(degenerate)).toBe(true)
  })

  it('非文字列・空は false', () => {
    expect(isOversizedMessage('')).toBe(false)
    expect(isOversizedMessage(null)).toBe(false)
    expect(isOversizedMessage(undefined)).toBe(false)
  })
})
