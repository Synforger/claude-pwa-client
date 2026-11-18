// @vitest-environment jsdom
//
// The attachments of a tab: an image picked is saved by imageStore and its item carries the URL the store keeps for
// it (the same URL the bubble shows after the send), an image taken back is deleted, and nothing here revokes a URL.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'

const putImage = vi.fn()
const peekImageURL = vi.fn()
const deleteImage = vi.fn()
vi.mock('../../../src/features/attachments/imageStore.js', () => ({
  putImage: (...args) => putImage(...args),
  peekImageURL: (...args) => peekImageURL(...args),
  deleteImage: (...args) => deleteImage(...args),
}))

import { useAttachments } from '../../../src/features/attachments/useAttachments.js'
import { setAttachments, getSnapshot } from '../../../src/state/ephemeral.js'

const SID = 'ses_att'

const pick = (...files) => ({ target: { files, value: 'C:\\fakepath\\x' } })
const pngFile = (name) => new File(['png'], name, { type: 'image/png' })

let revokeObjectURL

beforeEach(() => {
  putImage.mockReset()
  peekImageURL.mockReset()
  deleteImage.mockReset().mockResolvedValue(undefined)
  revokeObjectURL = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {})
  setAttachments(SID, [])
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('useAttachments', () => {
  it('carries the image id and the store\'s URL for an image, and no URL for a text file', async () => {
    putImage.mockResolvedValue('img1')
    peekImageURL.mockReturnValue('blob:store/img1')
    const { result } = renderHook(() => useAttachments({ id: SID }))
    const image = pngFile('shot.png')
    const text = new File(['hello'], 'notes.txt', { type: 'text/plain' })

    await act(async () => { await result.current.handleFileSelect(pick(image, text)) })

    const items = getSnapshot().attachments[SID]
    expect(items).toEqual([
      { file: image, url: 'blob:store/img1', imageId: 'img1' },
      { file: text, url: null, imageId: null },
    ])
    expect(putImage).toHaveBeenCalledTimes(1)
    expect(putImage).toHaveBeenCalledWith(image)
  })

  it('still adds an image the store could not save, without a preview', async () => {
    putImage.mockRejectedValue(new Error('no space'))
    const { result } = renderHook(() => useAttachments({ id: SID }))
    const image = pngFile('shot.png')

    await act(async () => { await result.current.handleFileSelect(pick(image)) })

    expect(getSnapshot().attachments[SID]).toEqual([{ file: image, url: null, imageId: null }])
  })

  it('deletes an image taken back before it was sent, and only that one', async () => {
    putImage.mockResolvedValueOnce('img1').mockResolvedValueOnce('img2')
    peekImageURL.mockImplementation((id) => `blob:store/${id}`)
    const { result } = renderHook(() => useAttachments({ id: SID }))
    await act(async () => { await result.current.handleFileSelect(pick(pngFile('a.png'), pngFile('b.png'))) })

    act(() => { result.current.removeAttachment(SID, 0) })

    expect(deleteImage).toHaveBeenCalledTimes(1)
    expect(deleteImage).toHaveBeenCalledWith('img1')
    expect(getSnapshot().attachments[SID].map(item => item.imageId)).toEqual(['img2'])
  })

  it('takes back a text file without touching the store', async () => {
    const { result } = renderHook(() => useAttachments({ id: SID }))
    const text = new File(['hello'], 'notes.txt', { type: 'text/plain' })
    await act(async () => { await result.current.handleFileSelect(pick(text)) })

    act(() => { result.current.removeAttachment(SID, 0) })

    expect(deleteImage).not.toHaveBeenCalled()
    expect(getSnapshot().attachments[SID]).toEqual([])
  })

  it('revokes no URL when the attachments are cleared after a send, or when the tab unmounts', async () => {
    putImage.mockResolvedValue('img1')
    peekImageURL.mockReturnValue('blob:store/img1')
    const { result, unmount } = renderHook(() => useAttachments({ id: SID }))
    await act(async () => { await result.current.handleFileSelect(pick(pngFile('a.png'))) })

    act(() => { result.current.clearAttachments(SID) })
    unmount()

    expect(revokeObjectURL).not.toHaveBeenCalled()
    expect(deleteImage).not.toHaveBeenCalled()
  })
})
