// @vitest-environment jsdom
//
// slack:// のリンクは、 押すと Slack のアプリが開く。 安全なスキームなので消さずに描き、 同じタブのまま OS に渡す。
// 危ないスキームは今までどおり消す。
import { describe, it, expect, afterEach } from 'vitest'
import { render, cleanup } from '@testing-library/react'
import MessageRenderer from '../../../src/features/chat/MessageRenderer.jsx'

afterEach(cleanup)

describe('slack:// links in a message', () => {
  it('keeps a slack:// link as written', () => {
    const { container } = render(
      <MessageRenderer text="[open in Slack](slack://channel?team=T0001&id=C0001)" onOpenFile={() => {}} />)
    const link = container.querySelector('a')
    expect(link.getAttribute('href')).toBe('slack://channel?team=T0001&id=C0001')
    expect(link.textContent).toBe('open in Slack')
    // the same tab hands it to the OS: a new tab would be left blank once the app opens
    expect(link.hasAttribute('target')).toBe(false)
  })

  it('still opens a web link in a new tab', () => {
    const { container } = render(<MessageRenderer text="[web](https://example.com/a)" onOpenFile={() => {}} />)
    expect(container.querySelector('a').getAttribute('target')).toBe('_blank')
  })

  it('still drops a javascript: link', () => {
    const { container } = render(<MessageRenderer text="[x](javascript:alert(1))" onOpenFile={() => {}} />)
    expect(container.querySelector('a')?.getAttribute('href') || '').not.toMatch(/^javascript:/i)
  })
})
