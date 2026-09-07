// @vitest-environment jsdom
//
// 長文の折りたたみが「markdown のまま」であることを固定する test (= 2026-09-08)。
//
// 背景: 旧実装は 1 つの閾値で「重さ対策」 と「読みやすさのための折りたたみ」 を兼ねており、
// 超えたメッセージは markdown を通さず <pre> に倒れていた。 展開ボタンを押しても生の
// markdown が出るので、 長い返答が読めない状態だった。 ここでは畳んだ状態と展開した状態の
// 両方で markdown 要素が DOM に出ることを見る。
import { describe, it, expect, afterEach } from 'vitest'
import { render, cleanup, fireEvent } from '@testing-library/react'
import MessageRenderer, { COLLAPSE_CHARS, PLAIN_FALLBACK_CHARS } from './MessageRenderer.jsx'

afterEach(cleanup)

// 見出し + 表 + コードフェンスを持つ長文を作る (= 先頭に markdown 要素、 末尾に目印)。
function longMarkdown(chars) {
  const head = [
    '## 見出し',
    '',
    '| a | b |',
    '| - | - |',
    '| 1 | 2 |',
    '',
    '```js',
    'const a = 1',
    '```',
    '',
  ].join('\n')
  const filler = []
  while (head.length + filler.join('\n\n').length < chars) {
    filler.push('本文の段落です。'.repeat(10))
  }
  return `${head}\n${filler.join('\n\n')}\n\n### 末尾の見出し\n`
}

describe('長文の折りたたみ', () => {
  it('閾値超えは畳まれるが、 畳んだ状態でも markdown で描画される', () => {
    const text = longMarkdown(COLLAPSE_CHARS + 2_000)
    const { container } = render(<MessageRenderer text={text} onOpenFile={() => {}} />)
    // 畳まれている印 = 展開ボタン
    const toggle = container.querySelector('.md-collapse-toggle')
    expect(toggle).not.toBeNull()
    // markdown を通っている (= plain の <pre class="md-plain"> ではない)
    expect(container.querySelector('.md-plain')).toBeNull()
    expect(container.querySelector('h2')).not.toBeNull()
    expect(container.querySelector('table')).not.toBeNull()
    // プレビューなので末尾はまだ出ていない
    expect(container.textContent).not.toContain('末尾の見出し')
  })

  it('展開しても markdown のまま全文が出る', () => {
    const text = longMarkdown(COLLAPSE_CHARS + 2_000)
    const { container } = render(<MessageRenderer text={text} onOpenFile={() => {}} />)
    fireEvent.click(container.querySelector('.md-collapse-toggle'))
    expect(container.querySelector('.md-plain')).toBeNull()
    expect(container.querySelector('h2')).not.toBeNull()
    // 末尾の見出しが markdown 要素として出ている (= 生テキストではない)
    const headings = [...container.querySelectorAll('h3')].map((el) => el.textContent)
    expect(headings).toContain('末尾の見出し')
  })

  it('日常の長文 (= 閾値以下) は畳まれない', () => {
    const text = longMarkdown(COLLAPSE_CHARS - 1_500).slice(0, COLLAPSE_CHARS - 100)
    const { container } = render(<MessageRenderer text={text} onOpenFile={() => {}} />)
    expect(container.querySelector('.md-collapse-toggle')).toBeNull()
    expect(container.querySelector('h2')).not.toBeNull()
  })

  it('degeneration 級だけは従来どおり plain へ退避する', () => {
    const text = 'court\n\n'.repeat(Math.ceil(PLAIN_FALLBACK_CHARS / 5))
    const { container } = render(<MessageRenderer text={text} onOpenFile={() => {}} />)
    expect(container.querySelector('.md-plain')).not.toBeNull()
    expect(container.querySelector('.md-collapse-toggle')).toBeNull()
  })
})
