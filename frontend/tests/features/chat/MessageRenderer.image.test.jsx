// @vitest-environment jsdom
//
// 返事の中の画像 (= `![説明](出どころ)`)。 Mac の path は backend の画像の口から読み、 http / https はそのまま出す。
// 埋め込み (= data:) と相対の path は出さずに説明の文字を出す。 押すと、 Mac の画像は file のプレビューで開く。
import { describe, it, expect, afterEach, vi } from 'vitest'
import { render, cleanup, fireEvent } from '@testing-library/react'
import MessageRenderer, { imageSource } from '../../../src/features/chat/MessageRenderer.jsx'
import { apiUrl } from '../../../src/_common/api.js'

afterEach(cleanup)

const raw = (path) => apiUrl(`/file/raw?path=${encodeURIComponent(path)}`)

describe('imageSource — where an image is read from', () => {
  it('reads a path on the Mac through the image endpoint', () => {
    expect(imageSource('/srv/shared/shot.png')).toBe(raw('/srv/shared/shot.png'))
    expect(imageSource('~/Pictures/a b.png')).toBe(raw('~/Pictures/a b.png'))
    expect(imageSource('file:///srv/shared/a%20b.png')).toBe(raw('/srv/shared/a b.png'))
  })

  it('keeps an http or https address as it is', () => {
    expect(imageSource('https://example.com/a.png')).toBe('https://example.com/a.png')
    expect(imageSource('http://example.com/a.png')).toBe('http://example.com/a.png')
  })

  it('shows nothing for an embedded image, a relative path, a protocol-relative address or a script', () => {
    expect(imageSource('data:image/png;base64,AAAA')).toBe('')
    expect(imageSource('images/a.png')).toBe('')
    expect(imageSource('//example.com/a.png')).toBe('')
    expect(imageSource('javascript:alert(1)')).toBe('')
    expect(imageSource('')).toBe('')
  })
})

describe('images in a message', () => {
  it('shows a Mac image and opens it in the file preview when tapped', () => {
    const onOpenFile = vi.fn()
    const { container } = render(
      <MessageRenderer text={'the chart:\n\n![chart](/srv/shared/chart.png)'} onOpenFile={onOpenFile} />)
    const img = container.querySelector('img.md-image')
    expect(img.getAttribute('src')).toBe(raw('/srv/shared/chart.png'))
    expect(img.getAttribute('alt')).toBe('chart')
    fireEvent.click(img)
    expect(onOpenFile).toHaveBeenCalledWith('/srv/shared/chart.png')
  })

  it('shows a web image and opens it in a new tab when tapped', () => {
    const open = vi.spyOn(window, 'open').mockImplementation(() => null)
    const { container } = render(<MessageRenderer text="![logo](https://example.com/logo.png)" onOpenFile={() => {}} />)
    const img = container.querySelector('img.md-image')
    expect(img.getAttribute('src')).toBe('https://example.com/logo.png')
    fireEvent.click(img)
    expect(open).toHaveBeenCalledWith('https://example.com/logo.png', '_blank', 'noreferrer')
    open.mockRestore()
  })

  it('shows the description instead of an embedded image', () => {
    const { container } = render(<MessageRenderer text="![a dot](data:image/png;base64,AAAA)" onOpenFile={() => {}} />)
    expect(container.querySelector('img')).toBeNull()
    expect(container.querySelector('.md-image-missing').textContent).toBe('🖼 a dot')
  })

  it('shows the description when the image cannot be read', () => {
    const { container } = render(<MessageRenderer text="![gone](/srv/shared/gone.png)" onOpenFile={() => {}} />)
    fireEvent.error(container.querySelector('img.md-image'))
    expect(container.querySelector('img')).toBeNull()
    expect(container.querySelector('.md-image-missing').textContent).toBe('🖼 gone')
  })
})
