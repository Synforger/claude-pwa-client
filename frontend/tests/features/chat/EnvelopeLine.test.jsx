// @vitest-environment jsdom
//
// EnvelopeLine (= 封筒の発話の 1 行) の試験。 開く行・押すと別の画面が開く行・中身の無い行の 3 通りの
// 印と開閉、 本文の頭の取り出しを見る。 MessageItem 経由の描画は MessageItem.render.test.jsx が見る。
import { describe, it, expect, afterEach, vi } from 'vitest'
import { render, cleanup, fireEvent } from '@testing-library/react'
import { EnvelopeLine, firstFilledLine } from '../../../src/features/chat/EnvelopeLine.jsx'

afterEach(cleanup)

describe('firstFilledLine', () => {
  it('skips blank lines and trims the line it finds', () => {
    expect(firstFilledLine('\n  \n  the first line  \nthe second')).toBe('the first line')
  })

  it('is empty when the text has no filled line', () => {
    expect(firstFilledLine('')).toBe('')
    expect(firstFilledLine('\n  \n')).toBe('')
  })
})

describe('EnvelopeLine that opens', () => {
  const folded = (props) => render(
    <EnvelopeLine icon="✉" label="From tools" labelTestId="label" tail="the head" tailTestId="head"
      toggleTestId="toggle" body={<p>the whole text</p>} bodyTestId="body" {...props} />,
  )

  it('is folded by default: a ▸ mark, the label and the head, and no body', () => {
    const { getByTestId, queryByTestId, container } = folded()
    expect(getByTestId('toggle').getAttribute('aria-expanded')).toBe('false')
    expect(getByTestId('toggle').querySelector('.tool-marker').textContent).toBe('▸')
    expect(getByTestId('toggle').textContent).toBe('▸✉ From tools · the head')
    expect(queryByTestId('body')).toBeNull()
    expect(container.textContent).not.toContain('the whole text')
    expect(container.querySelector('.bubble')).toBeNull()
  })

  it('opens on a tap: a ▾ mark and the body, and the head leaves the line', () => {
    const { getByTestId, queryByTestId } = folded()
    fireEvent.click(getByTestId('toggle'))
    expect(getByTestId('toggle').getAttribute('aria-expanded')).toBe('true')
    expect(getByTestId('toggle').querySelector('.tool-marker').textContent).toBe('▾')
    expect(getByTestId('body').textContent).toBe('the whole text')
    expect(queryByTestId('head')).toBeNull()
    expect(getByTestId('label').textContent).toBe('From tools')
  })

  it('folds again on a second tap', () => {
    const { getByTestId, queryByTestId } = folded()
    fireEvent.click(getByTestId('toggle'))
    fireEvent.click(getByTestId('toggle'))
    expect(getByTestId('toggle').getAttribute('aria-expanded')).toBe('false')
    expect(queryByTestId('body')).toBeNull()
    expect(getByTestId('head').textContent).toBe('the head')
  })

  it('leaves out the separator and the head when there is no head', () => {
    const { getByTestId } = folded({ tail: '' })
    expect(getByTestId('toggle').textContent).toBe('▸✉ From tools')
  })
})

describe('EnvelopeLine that opens another screen', () => {
  it('shows a ↗ mark and calls onOpen on a tap, with no body to open', () => {
    const onOpen = vi.fn()
    const { getByTestId, container } = render(
      <EnvelopeLine icon="📌" label="Ticket tk-1 from tools" labelTestId="label" onOpen={onOpen} openTestId="link" />,
    )
    expect(getByTestId('link').textContent).toBe('↗📌 Ticket tk-1 from tools')
    expect(container.querySelector('details')).toBeNull()
    fireEvent.click(getByTestId('link'))
    expect(onOpen).toHaveBeenCalledTimes(1)
  })
})

describe('EnvelopeLine with nothing to open', () => {
  it('shows a · mark, the label and the tail joined by the separator given', () => {
    const { getByTestId, container } = render(
      <EnvelopeLine label="Tier tab opened" labelTestId="label" tail="projects/music" tailTestId="tail" tailSeparator=": " />,
    )
    expect(getByTestId('label').parentElement.textContent).toBe('·Tier tab opened: projects/music')
    expect(getByTestId('tail').textContent).toBe('projects/music')
    expect(container.querySelector('details')).toBeNull()
    expect(container.querySelector('button')).toBeNull()
  })
})
