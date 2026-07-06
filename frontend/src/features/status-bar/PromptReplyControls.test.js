// freeTextDigit (= pane excerpt から "N. Type something" の N を読む) の契約 test。
// 位置 (= 最後の数字) では判定しない: claude の TUI は "Type something" の後に
// "Chat about this" 等を足すことがある (= 2026-07-06 実測で 5 択化)。
import { describe, it, expect } from 'vitest'
import { freeTextDigit } from './PromptReplyControls.jsx'

describe('freeTextDigit', () => {
  it('Type something の数字を位置に依存せず抽出する', () => {
    const excerpt = [
      '  1. 選択肢 A',
      '  2. 選択肢 B',
      '  3. 選択肢 C',
      '❯ 4. Type something.',
      '  5. Chat about this',
    ].join('\n')
    expect(freeTextDigit({ excerpt })).toBe('4')
  })

  it('Type something が無ければ null (= 通常 picker では発火しない)', () => {
    expect(freeTextDigit({ excerpt: '❯ 1. Yes\n  2. No' })).toBe(null)
    expect(freeTextDigit({ excerpt: '' })).toBe(null)
    expect(freeTextDigit(null)).toBe(null)
  })
})
