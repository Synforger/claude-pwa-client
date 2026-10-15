import { describe, it, expect } from 'vitest'
import { hideMarks } from './marks.js'

const MARKS = ['calm', 'happy', 'soft']

describe('hideMarks — marks are taken out of the text that is shown', () => {
  it('takes a mark off the head of a line', () => {
    expect(hideMarks('[happy] できたよ！', MARKS)).toBe('できたよ！')
  })

  it('takes a mark off after a sentence ends, in the same line', () => {
    expect(hideMarks('できたよ！ [soft] ゆっくり休んでね。[calm]次は明日。', MARKS)).toBe('できたよ！ ゆっくり休んでね。次は明日。')
  })

  it('takes a mark off after the symbol of a heading, a bullet, a number or a quote', () => {
    expect(hideMarks('## [happy] 結果\n- [calm] 一つ目\n1. [soft] 二つ目\n> [happy] 引用', MARKS))
      .toBe('## 結果\n- 一つ目\n1. 二つ目\n> 引用')
  })

  it('leaves a bracket that is no mark of this agent', () => {
    expect(hideMarks('[angry] これは印ではない。[1] 脚注。', MARKS)).toBe('[angry] これは印ではない。[1] 脚注。')
  })

  it('leaves a mark in the middle of a sentence, as the voice reads it', () => {
    expect(hideMarks('印は [happy] のように書く。', MARKS)).toBe('印は [happy] のように書く。')
  })

  it('leaves code alone: a fenced block and inline code', () => {
    const text = '[happy] 例はこれ。\n```\n[happy] in code\n```\n`[calm] inline` はそのまま。'
    expect(hideMarks(text, MARKS)).toBe('例はこれ。\n```\n[happy] in code\n```\n`[calm] inline` はそのまま。')
  })

  it('takes a mark off after a sentence that ends in inline code and a stop', () => {
    expect(hideMarks('場所は `a.md` だよ。[happy] 見てね！', MARKS)).toBe('場所は `a.md` だよ。見てね！')
  })

  it('returns the text as it is when the agent has no marks', () => {
    expect(hideMarks('[happy] そのまま。', [])).toBe('[happy] そのまま。')
    expect(hideMarks('[happy] そのまま。', undefined)).toBe('[happy] そのまま。')
    expect(hideMarks('', MARKS)).toBe('')
    expect(hideMarks(undefined, MARKS)).toBe(undefined)
  })

  it('takes off a mark with values, at the head and after a stop', () => {
    expect(hideMarks('[happy i=1.2 s=0.9] やった！[happy t=1.4] 次も！', MARKS)).toBe('やった！次も！')
    expect(hideMarks('- [happy intonationScale=0.6] そうだね。', MARKS)).toBe('- そうだね。')
  })

  it('leaves a bracket that only looks like a mark with values', () => {
    expect(hideMarks('[voice i=1.2] 聞こえる？', MARKS)).toBe('[voice i=1.2] 聞こえる？')
    expect(hideMarks('[happy i=] 途中。', MARKS)).toBe('[happy i=] 途中。')
  })

  it('ignores a name that could not be a mark', () => {
    expect(hideMarks('[a|b] x', ['a|b', '.*'])).toBe('[a|b] x')
  })
})
