// @vitest-environment jsdom
//
// メモの描き方 (= asWritten) を固定する test。 markdown として描いたまま、 長さで畳まず、
// 段落の改行と空白を書いたとおりに残す。
import { describe, it, expect, afterEach } from 'vitest'
import { render, cleanup } from '@testing-library/react'
import MessageRenderer, { COLLAPSE_CHARS, PLAIN_FALLBACK_CHARS } from './MessageRenderer.jsx'

afterEach(cleanup)

const NBSP = ' '
const note = (text) => render(<MessageRenderer text={text} onOpenFile={() => {}} asWritten />).container
// 描いた段落を、 改行の印で行に割って読む (= 印の後ろに部品が置く改行の文字は、 ブラウザでは詰められて
// 見えないので数えない)
const lines = (el) => {
  const copy = el.cloneNode(true)
  copy.querySelectorAll('br').forEach((br) => br.replaceWith('\u2029'))
  return copy.textContent.replace(/\n/g, '').split('\u2029')
}

describe('メモの描き方', () => {
  it('段落の改行を改行のまま、 行頭と続く空白を詰めずに出す', () => {
    const c = note('root/\n├─ a/      → one\n  indented\n└─ ccc/    → two')
    const p = c.querySelector('p')
    expect(p.querySelectorAll('br')).toHaveLength(3)
    expect(lines(p)).toEqual([
      'root/',
      `├─ a/${NBSP.repeat(6)}→ one`,
      `${NBSP.repeat(2)}indented`,
      `└─ ccc/${NBSP.repeat(4)}→ two`,
    ])
  })

  it('段落の 1 行目の行頭の空白も残す', () => {
    expect(lines(note('  first\nsecond').querySelector('p'))).toEqual([`${NBSP.repeat(2)}first`, 'second'])
  })

  it('見出し・表・リストは markdown として描く', () => {
    const c = note('# T\n\n| a | b |\n| - | - |\n| 1 | 2 |\n\n- x\n- y')
    expect(c.querySelector('h1').textContent).toBe('T')
    expect(c.querySelector('table')).not.toBeNull()
    expect([...c.querySelectorAll('li')].map((li) => li.textContent)).toEqual(['x', 'y'])
  })

  it('リストの続きの行は、 字下げを書式として読み、 改行だけ残す', () => {
    const li = note('- a\n  b').querySelector('li')
    expect(lines(li)).toEqual(['a', 'b'])
  })

  it('path はタップで開ける形のまま', () => {
    const link = note('see ~/a/b.md\nnext').querySelector('.file-link')
    expect(link.textContent).toBe('~/a/b.md')
  })

  it('長くても畳まず、 素の文へも退かない', () => {
    for (const size of [COLLAPSE_CHARS + 2_000, PLAIN_FALLBACK_CHARS + 2_000]) {
      const text = `# head\n\n${'本文の段落です。\n'.repeat(Math.ceil(size / 9))}\n## tail\n`
      const c = note(text)
      expect(c.querySelector('.md-collapse-toggle')).toBeNull()
      expect(c.querySelector('.md-oversized')).toBeNull()
      expect(c.querySelector('h2').textContent).toBe('tail')
    }
  })
})
