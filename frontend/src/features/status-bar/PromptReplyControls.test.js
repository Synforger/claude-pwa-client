// cursorOnTypeSomething (= カーソルが "Type something" 行に乗っているかを excerpt から
// 導出する) の契約 test。 ローカル flag でなく pane の真値から表示状態を決めるのが要点
// (= タップ / ↑↓ / 端末直叩きのどの経路でも表示がズレない)。
import { describe, it, expect } from 'vitest'
import { cursorOnTypeSomething } from './PromptReplyControls.jsx'

describe('cursorOnTypeSomething', () => {
  it('カーソルが Type something 行に乗っている時だけ true', () => {
    const on = [
      '  1. 選択肢 A',
      '  2. 選択肢 B',
      '❯ 4. Type something.',
      '  5. Chat about this',
    ].join('\n')
    expect(cursorOnTypeSomething({ excerpt: on })).toBe(true)

    const off = [
      '❯ 1. 選択肢 A',
      '  2. 選択肢 B',
      '  4. Type something.',
      '  5. Chat about this',
    ].join('\n')
    expect(cursorOnTypeSomething({ excerpt: off })).toBe(false)
  })

  it('Type something が無い通常 picker では常に false', () => {
    expect(cursorOnTypeSomething({ excerpt: '❯ 1. Yes\n  2. No' })).toBe(false)
    expect(cursorOnTypeSomething({ excerpt: '' })).toBe(false)
    expect(cursorOnTypeSomething(null)).toBe(false)
  })
})
