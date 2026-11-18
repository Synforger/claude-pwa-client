// @vitest-environment jsdom
//
// The images of a bubble: shown by the one URL the store keeps for each image, the same one every time the bubble
// mounts, and never revoked here.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, waitFor } from '@testing-library/react'

const getImageURL = vi.fn()
const peekImageURL = vi.fn()
vi.mock('../../../src/features/attachments/imageStore.js', () => ({
  getImageURL: (...args) => getImageURL(...args),
  peekImageURL: (...args) => peekImageURL(...args),
}))

import AttachedImages from '../../../src/features/attachments/AttachedImages.jsx'

const srcs = (container) => [...container.querySelectorAll('img')].map(img => img.getAttribute('src'))

let revokeObjectURL

beforeEach(() => {
  getImageURL.mockReset().mockImplementation(async (id) => `blob:store/${id}`)
  peekImageURL.mockReset().mockReturnValue(null)
  revokeObjectURL = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {})
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('AttachedImages', () => {
  it('shows each image by the store\'s URL once it is ready', async () => {
    const { container } = render(<AttachedImages imageRefs={['a', 'b']} />)

    await waitFor(() => expect(srcs(container)).toEqual(['blob:store/a', 'blob:store/b']))
  })

  it('shows the same URLs when the bubble mounts again, and revokes none on the way', async () => {
    const first = render(<AttachedImages imageRefs={['a', 'b']} />)
    await waitFor(() => expect(srcs(first.container)).toEqual(['blob:store/a', 'blob:store/b']))
    first.unmount()

    const second = render(<AttachedImages imageRefs={['a', 'b']} />)
    await waitFor(() => expect(srcs(second.container)).toEqual(['blob:store/a', 'blob:store/b']))

    expect(revokeObjectURL).not.toHaveBeenCalled()
  })

  it('shows an image that is already ready on the first render, with no placeholder', () => {
    peekImageURL.mockImplementation((id) => `blob:store/${id}`)

    const { container } = render(<AttachedImages imageRefs={['a']} />)

    expect(srcs(container)).toEqual(['blob:store/a'])
  })

  it('leaves a placeholder where the store has no image', async () => {
    getImageURL.mockResolvedValue(null)

    const { container } = render(<AttachedImages imageRefs={['gone']} />)

    await waitFor(() => expect(getImageURL).toHaveBeenCalledWith('gone'))
    expect(srcs(container)).toEqual([])
    expect(container.querySelectorAll('.msg-image').length).toBe(1)
  })

  it('shows the legacy image URLs of a message that has no image ids', () => {
    const { container } = render(<AttachedImages imageUrls={['data:image/png;base64,AAAA']} />)

    expect(srcs(container)).toEqual(['data:image/png;base64,AAAA'])
    expect(getImageURL).not.toHaveBeenCalled()
  })
})
