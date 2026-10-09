// @vitest-environment jsdom
//
// 文の中の path は、 タップで開くリンクになる。 1 つの path は 1 つのリンクで、 1 回のタップで
// 開く処理が 1 回だけ走る (= 作ったリンクの中の文字をもう一度リンクにして、 入れ子にしない)。
import { describe, it, expect, afterEach, vi } from 'vitest'
import { render, cleanup, fireEvent } from '@testing-library/react'
import MessageRenderer from './MessageRenderer.jsx'

afterEach(cleanup)

describe('file paths in a message', () => {
  it('links a path once and opens it once per tap', () => {
    const onOpenFile = vi.fn()
    const { container } = render(<MessageRenderer text="see ~/docs/spec.md for details" onOpenFile={onOpenFile} />)
    const links = container.querySelectorAll('.file-link')
    expect(links).toHaveLength(1)
    expect(links[0].textContent).toBe('~/docs/spec.md')
    fireEvent.click(links[0])
    expect(onOpenFile).toHaveBeenCalledTimes(1)
    expect(onOpenFile).toHaveBeenCalledWith('~/docs/spec.md')
  })

  it('links every path of a line, and keeps the text between them', () => {
    const { container } = render(<MessageRenderer text="from ~/a/one.md to ~/b/two.md done" onOpenFile={() => {}} />)
    const links = [...container.querySelectorAll('.file-link')].map(el => el.textContent)
    expect(links).toEqual(['~/a/one.md', '~/b/two.md'])
    expect(container.textContent).toBe('from ~/a/one.md to ~/b/two.md done')
  })

  it('links a path written as inline code', () => {
    const { container } = render(<MessageRenderer text="open `~/a/one.md` now" onOpenFile={() => {}} />)
    const links = container.querySelectorAll('.file-link')
    expect(links).toHaveLength(1)
    expect(links[0].textContent).toBe('~/a/one.md')
  })
})
