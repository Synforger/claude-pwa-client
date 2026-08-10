import { describe, it, expect } from 'vitest'
import { toneFor } from './StatusStrip.jsx'

// 状態の文字列は会議ごとに人が書くので、 表記の揺れを前提に色を決める。
// 未知の語を既定色へ落とすのが肝 (= 知らない状態を「進行中」 に見せない)。
describe('toneFor', () => {
  it('maps the four known states', () => {
    expect(toneFor('異議')).toBe('objection')
    expect(toneFor('待機')).toBe('waiting')
    expect(toneFor('完了')).toBe('done')
    expect(toneFor('進行中')).toBe('running')
  })

  it('accepts english spellings', () => {
    expect(toneFor('waiting')).toBe('waiting')
    expect(toneFor('Running')).toBe('running')
  })

  it('falls back to unknown rather than guessing', () => {
    expect(toneFor('')).toBe('unknown')
    expect(toneFor(undefined)).toBe('unknown')
    expect(toneFor('なにか別の状態')).toBe('unknown')
  })
})
