// The attached images' store: an image is shown by one URL that every call hands out again until the image is deleted,
// and only then is it revoked (Chrome keeps a decoded copy for each URL it is shown, so a URL made again on every
// mount piles the copies up). Also: the thumbnail saved with the image, added to a record saved without one, and the
// image kept for the session when IndexedDB is unavailable.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { installFakeIndexedDB } from './fakeIndexedDB.js'

vi.mock('../../../src/features/attachments/imageResize.js', () => ({
  decodeBitmap: vi.fn(async () => null),
  drawToBlob: vi.fn(async () => null),
  makeThumbnail: vi.fn(async () => null),
  outputType: vi.fn(() => 'image/png'),
}))

const RESIZE_PATH = '../../../src/features/attachments/imageResize.js'
const STORE_PATH = '../../../src/features/attachments/imageStore.js'

let urlCount
let urlOf
let createObjectURL
let revokeObjectURL

/** A fresh copy of the store (its URL tables are module state), with the mocked drawing module it calls. */
async function loadStore() {
  vi.resetModules()
  const resize = await import(RESIZE_PATH)
  resize.makeThumbnail.mockReset().mockResolvedValue(null)
  const store = await import(STORE_PATH)
  return { resize, store }
}

const imageBlob = (text) => new Blob([text], { type: 'image/png' })

/** A record as an earlier page session left it in IndexedDB. */
function storedRecord({ thumb, thumbChecked = true, createdAt = 1 } = {}) {
  const blob = imageBlob('original')
  return { blob, ...(thumb ? { thumb } : {}), thumbChecked, mime: 'image/png', size: blob.size + (thumb ? thumb.size : 0), createdAt }
}

beforeEach(() => {
  urlCount = 0
  urlOf = new Map()
  createObjectURL = vi.spyOn(URL, 'createObjectURL').mockImplementation((blob) => {
    urlCount += 1
    const url = `blob:test/${urlCount}`
    urlOf.set(url, blob)
    return url
  })
  revokeObjectURL = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {})
})

afterEach(() => {
  vi.restoreAllMocks()
  delete globalThis.indexedDB
})

describe('putImage', () => {
  it('saves the image with its thumbnail and has the thumbnail\'s URL ready on return', async () => {
    const records = installFakeIndexedDB()
    const { resize, store } = await loadStore()
    const thumb = imageBlob('thumb')
    resize.makeThumbnail.mockResolvedValue(thumb)

    const id = await store.putImage(imageBlob('original'))

    const record = records.get(id)
    expect(record.thumb).toBe(thumb)
    expect(record.thumbChecked).toBe(true)
    expect(record.size).toBe(record.blob.size + thumb.size)
    const url = store.peekImageURL(id)
    expect(urlOf.get(url)).toBe(thumb)
    expect(createObjectURL).toHaveBeenCalledTimes(1)
  })

  it('shows the original when the image needs no thumbnail', async () => {
    const records = installFakeIndexedDB()
    const { store } = await loadStore()

    const id = await store.putImage(imageBlob('original'))

    expect(records.get(id).thumb).toBeUndefined()
    expect(records.get(id).thumbChecked).toBe(true)
    expect(urlOf.get(store.peekImageURL(id))).toBe(records.get(id).blob)
  })

  it('still returns an id, and keeps the image shown, when IndexedDB is unavailable', async () => {
    installFakeIndexedDB({ unavailable: true })
    const { store } = await loadStore()

    const id = await store.putImage(imageBlob('original'))

    expect(typeof id).toBe('string')
    expect(store.peekImageURL(id)).not.toBeNull()
  })
})

describe('getImageURL', () => {
  it('hands out the same URL on every call, one made in all', async () => {
    const records = installFakeIndexedDB()
    records.set('a', storedRecord({ thumb: imageBlob('thumb') }))
    const { store } = await loadStore()

    const [first, second] = await Promise.all([store.getImageURL('a'), store.getImageURL('a')])
    const third = await store.getImageURL('a')

    expect(second).toBe(first)
    expect(third).toBe(first)
    expect(store.peekImageURL('a')).toBe(first)
    expect(createObjectURL).toHaveBeenCalledTimes(1)
    expect(revokeObjectURL).not.toHaveBeenCalled()
  })

  it('gives the URL made by putImage, not another', async () => {
    installFakeIndexedDB()
    const { store } = await loadStore()
    const id = await store.putImage(imageBlob('original'))
    const made = store.peekImageURL(id)

    expect(await store.getImageURL(id)).toBe(made)
    expect(createObjectURL).toHaveBeenCalledTimes(1)
  })

  it('returns null for an image that is not stored, and asks the store again next time', async () => {
    const records = installFakeIndexedDB()
    const { store } = await loadStore()

    expect(await store.getImageURL('missing')).toBeNull()
    expect(store.peekImageURL('missing')).toBeNull()

    records.set('missing', storedRecord())
    expect(await store.getImageURL('missing')).not.toBeNull()
  })

  it('adds the thumbnail to a record saved without one, once', async () => {
    const records = installFakeIndexedDB()
    records.set('old', storedRecord({ thumbChecked: false }))
    const { resize, store } = await loadStore()
    const thumb = imageBlob('thumb')
    resize.makeThumbnail.mockResolvedValue(thumb)

    const url = await store.getImageURL('old')

    expect(urlOf.get(url)).toBe(thumb)
    expect(records.get('old').thumb).toBe(thumb)
    expect(records.get('old').thumbChecked).toBe(true)
    expect(records.get('old').size).toBe(records.get('old').blob.size + thumb.size)

    // A new page session finds the thumbnail in the record and makes none.
    const next = await loadStore()
    await next.store.getImageURL('old')
    expect(next.resize.makeThumbnail).not.toHaveBeenCalled()
  })

  it('notes that a record needs no thumbnail, and shows its original', async () => {
    const records = installFakeIndexedDB()
    records.set('old', storedRecord({ thumbChecked: false }))
    const { store } = await loadStore()

    const url = await store.getImageURL('old')

    expect(urlOf.get(url)).toBe(records.get('old').blob)
    expect(records.get('old').thumb).toBeUndefined()
    expect(records.get('old').thumbChecked).toBe(true)
  })
})

describe('deleteImage', () => {
  it('revokes the URL and removes the record', async () => {
    const records = installFakeIndexedDB()
    records.set('a', storedRecord())
    const { store } = await loadStore()
    const url = await store.getImageURL('a')

    await store.deleteImage('a')

    expect(revokeObjectURL).toHaveBeenCalledTimes(1)
    expect(revokeObjectURL).toHaveBeenCalledWith(url)
    expect(records.has('a')).toBe(false)
    expect(store.peekImageURL('a')).toBeNull()
    expect(await store.getImageURL('a')).toBeNull()
  })

  it('abandons a URL still being made: none is made and the caller gets null', async () => {
    const records = installFakeIndexedDB()
    records.set('a', storedRecord())
    const { store } = await loadStore()

    const pending = store.getImageURL('a')
    await store.deleteImage('a')

    expect(await pending).toBeNull()
    expect(createObjectURL).not.toHaveBeenCalled()
    expect(store.peekImageURL('a')).toBeNull()
  })

  it('revokes only the URL of the image it deletes', async () => {
    const records = installFakeIndexedDB()
    records.set('a', storedRecord())
    records.set('b', storedRecord())
    const { store } = await loadStore()
    await store.getImageURL('a')
    const kept = await store.getImageURL('b')

    await store.deleteImage('a')

    expect(revokeObjectURL).toHaveBeenCalledTimes(1)
    expect(store.peekImageURL('b')).toBe(kept)
  })
})

describe('the limits and the GC', () => {
  it('revokes the URL of the oldest image when a 101st image retires it', async () => {
    const records = installFakeIndexedDB()
    let now = 1_000
    vi.spyOn(Date, 'now').mockImplementation(() => (now += 1))
    const { store } = await loadStore()

    const ids = []
    for (let i = 0; i < 101; i++) ids.push(await store.putImage(imageBlob(`image ${i}`)))

    expect(records.has(ids[0])).toBe(false)
    expect(store.peekImageURL(ids[0])).toBeNull()
    expect(revokeObjectURL).toHaveBeenCalledTimes(1)
    expect(store.peekImageURL(ids[1])).not.toBeNull()
    expect(store.peekImageURL(ids[100])).not.toBeNull()
  })

  it('gcImages removes the images that no message holds, and revokes their URLs only', async () => {
    const records = installFakeIndexedDB()
    records.set('keep', storedRecord())
    records.set('drop1', storedRecord())
    records.set('drop2', storedRecord())
    const { store } = await loadStore()
    const kept = await store.getImageURL('keep')
    await store.getImageURL('drop1')

    const removed = await store.gcImages(['keep'])

    expect(removed).toBe(2)
    expect([...records.keys()]).toEqual(['keep'])
    expect(revokeObjectURL).toHaveBeenCalledTimes(1)
    expect(store.peekImageURL('keep')).toBe(kept)
    expect(store.peekImageURL('drop1')).toBeNull()
  })
})
