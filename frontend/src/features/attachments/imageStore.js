// Attached images: kept in IndexedDB as Blobs, so a message holds only an image ID. (A data URL in localStorage costs
// LZString compression time and quota.)
//
//   DB: cpc_images
//   ObjectStore: images (key = imageId,
//     value = { blob, thumb?, thumbChecked, mime, size, createdAt })
//   `blob` is the image as attached (scaled down when it is a very large photo). `thumb` is the small copy a bubble
//   and the attachment bar show (imageResize.js); it is absent when the image is already that small.
//
//   - putImage(file): saves the image and its thumbnail, returns the imageId
//   - getImageURL(id) / peekImageURL(id): the one URL an image is shown by
//   - deleteImage(id): removes the record and the URL
//   - listImageIds(): every ID (for the GC)
//   - gcImages(activeIds): removes every ID not in activeIds
//
// The URL of an image: one per imageId, made once and handed out again by every call until the image is deleted, which
// is the only time it is revoked. Chrome keeps a decoded copy of every picture it is shown by a blob URL, and it keeps
// it after the URL is revoked and the <img> is gone, so a URL made again on each mount (a conversation switched to
// and back) decodes the same picture again each time and the copies pile up in the renderer's native memory. One URL
// per image is decoded once.

import { decodeBitmap, drawToBlob, makeThumbnail, outputType } from './imageResize.js'
import { fitScale } from './imageGeometry.js'

const DB_NAME = 'cpc_images'
const DB_VERSION = 1
const STORE = 'images'

// 自動 bounded: 放置で IndexedDB が無限に膨らまないよう putImage 時に上限を強制する。
// 古い順 (createdAt) に退役させる (= 古い履歴の画像は表示外なので degrade で許容)。
const MAX_IMAGES = 100
const MAX_TOTAL_BYTES = 100 * 1024 * 1024 // 100MB
// この閾値を超える画像は保存前に canvas で縮小する (= 端末カメラの数 MB 画像対策)。
const DOWNSCALE_THRESHOLD = 2 * 1024 * 1024 // 2MB
const MAX_DIM = 2048 // 長辺の上限 px

function openDB() {
  return new Promise((resolve, reject) => {
    if (typeof indexedDB === 'undefined') {
      reject(new Error('IndexedDB unavailable'))
      return
    }
    const req = indexedDB.open(DB_NAME, DB_VERSION)
    req.onupgradeneeded = (e) => {
      const db = e.target.result
      if (!db.objectStoreNames.contains(STORE)) {
        db.createObjectStore(STORE) // key を外部指定
      }
    }
    req.onsuccess = () => resolve(req.result)
    req.onerror = () => reject(req.error)
  })
}

function txStore(db, mode) {
  return db.transaction(STORE, mode).objectStore(STORE)
}

function genImageId() {
  // 32 hex chars。 衝突確率は無視できる
  if (crypto && crypto.randomUUID) return crypto.randomUUID().replace(/-/g, '')
  return Math.random().toString(36).slice(2) + Date.now().toString(36)
}

// 大きい画像 (= DOWNSCALE_THRESHOLD 超) を長辺 MAX_DIM に収まるよう canvas で縮小する。
// 画像でない / 縮小不要 / 縮小に失敗した場合は元 File をそのまま返す (= 安全側に倒す)。
async function _downscaleIfLarge(file) {
  if (!file || !file.type || !file.type.startsWith('image/')) return file
  if (file.size <= DOWNSCALE_THRESHOLD) return file
  const bmp = await decodeBitmap(file)
  if (!bmp) return file
  try {
    const scale = fitScale(bmp.width, bmp.height, MAX_DIM)
    if (scale >= 1) return file // 既に十分小さい
    const w = Math.round(bmp.width * scale)
    const h = Math.round(bmp.height * scale)
    const blob = await drawToBlob(bmp, { x: 0, y: 0, width: bmp.width, height: bmp.height }, w, h, outputType(file))
    // 縮小したのに元より大きければ元を採用 (= まれだが理論上あり得る)
    if (blob && blob.size < file.size) return blob
    return file
  } catch {
    return file
  } finally {
    if (bmp.close) bmp.close()
  }
}

// 上限内ならカーソル全走査を省略するための in-memory ヘッダキャッシュ。
// セッション初回 (cache 無し) だけ全件走査、 以降は putImage / deleteImage で増減更新。
let _capsCache = null // {count, total, recs: [{id, createdAt, size}]} | null

async function _loadCapsCache(db) {
  if (_capsCache) return _capsCache
  const recs = await new Promise((resolve, reject) => {
    const out = []
    const req = txStore(db, 'readonly').openCursor()
    req.onsuccess = (e) => {
      const cur = e.target.result
      if (!cur) { resolve(out); return }
      const v = cur.value || {}
      out.push({ id: cur.key, createdAt: v.createdAt || 0, size: v.size || (v.blob ? v.blob.size : 0) })
      cur.continue()
    }
    req.onerror = () => reject(req.error)
  })
  _capsCache = {
    recs,
    count: recs.length,
    total: recs.reduce((s, r) => s + r.size, 0),
  }
  return _capsCache
}

// 上限超過分を古い順に退役させる。 putImage の直後に呼ぶ。
// in-memory cache で上限内なら全件カーソル走査をスキップする (= putImage 毎の数十ms ブロック対策)。
async function _enforceCaps(db, newRec) {
  const cache = await _loadCapsCache(db)
  // The first call of a session loads every record, the one just saved included, so it is already counted then.
  if (newRec && !cache.recs.some(r => r.id === newRec.id)) {
    cache.recs.push(newRec)
    cache.count += 1
    cache.total += newRec.size
  }
  if (cache.count <= MAX_IMAGES && cache.total <= MAX_TOTAL_BYTES) return
  cache.recs.sort((a, b) => a.createdAt - b.createdAt) // 古い順
  while ((cache.count > MAX_IMAGES || cache.total > MAX_TOTAL_BYTES) && cache.recs.length > 0) {
    const r = cache.recs.shift()
    try { await deleteImage(r.id) } catch { /* ignore */ }
    cache.count -= 1
    cache.total -= r.size
  }
}

// The URL of each image: the ready ones, and the ones being made (so two callers asking at once get one URL).
const _urlByImageId = new Map() // imageId → URL
const _urlLoadByImageId = new Map() // imageId → { promise } while its URL is being made

function _registerURL(id, blob) {
  const url = URL.createObjectURL(blob)
  _urlByImageId.set(id, url)
  return url
}

// Drops the URL of an image for good, and abandons a URL still being made for it.
function _forgetURL(id) {
  _urlLoadByImageId.delete(id)
  const url = _urlByImageId.get(id)
  if (url) {
    URL.revokeObjectURL(url)
    _urlByImageId.delete(id)
  }
}

function _readRecord(db, id) {
  return new Promise((resolve, reject) => {
    const req = txStore(db, 'readonly').get(id)
    req.onsuccess = () => resolve(req.result)
    req.onerror = () => reject(req.error)
  })
}

// Adds the thumbnail (or the note that there is none to make) to a record saved without one. Reads and writes in one
// transaction, so an image deleted in between is not written back.
async function _saveThumbnail(db, id, thumb) {
  await new Promise((resolve, reject) => {
    const store = txStore(db, 'readwrite')
    const read = store.get(id)
    read.onsuccess = () => {
      const current = read.result
      if (!current) { resolve(); return }
      const size = (current.size || (current.blob ? current.blob.size : 0)) + (thumb ? thumb.size : 0)
      const write = store.put({ ...current, ...(thumb ? { thumb } : {}), thumbChecked: true, size }, id)
      write.onsuccess = () => resolve()
      write.onerror = () => reject(write.error)
    }
    read.onerror = () => reject(read.error)
  })
  const entry = _capsCache && thumb ? _capsCache.recs.find(r => r.id === id) : null
  if (entry) {
    entry.size += thumb.size
    _capsCache.total += thumb.size
  }
}

// The URL's blob for a stored image: the thumbnail, made now for a record saved before thumbnails existed.
async function _loadImageURL(id, load) {
  try {
    const db = await openDB()
    const rec = await _readRecord(db, id)
    if (!rec || !rec.blob) return null
    let shown = rec.thumb || rec.blob
    if (!rec.thumbChecked) {
      const thumb = await makeThumbnail(rec.blob).catch(() => null)
      await _saveThumbnail(db, id, thumb).catch(() => {})
      shown = thumb || rec.blob
    }
    if (_urlLoadByImageId.get(id) !== load) return null // deleted while it was being made
    return _registerURL(id, shown)
  } finally {
    if (_urlLoadByImageId.get(id) === load) _urlLoadByImageId.delete(id)
  }
}

/** Saves an attached image with its thumbnail and returns its imageId; its URL is ready (peekImageURL) on return. */
export async function putImage(file) {
  const id = genImageId()
  const blob = await _downscaleIfLarge(file)
  const thumb = await makeThumbnail(blob).catch(() => null)
  // An image that cannot be stored (IndexedDB unavailable) is still shown this session by its URL.
  _registerURL(id, thumb || blob)
  const record = {
    blob,
    ...(thumb ? { thumb } : {}),
    thumbChecked: true,
    mime: blob.type || file.type || 'application/octet-stream',
    size: blob.size + (thumb ? thumb.size : 0),
    createdAt: Date.now(),
  }
  try {
    const db = await openDB()
    await new Promise((resolve, reject) => {
      const req = txStore(db, 'readwrite').put(record, id)
      req.onsuccess = () => resolve()
      req.onerror = () => reject(req.error)
    })
    await _enforceCaps(db, { id, createdAt: record.createdAt, size: record.size }).catch(() => {})
  } catch { /* not stored: the image is gone after a reload */ }
  return id
}

/** The URL of an image if it is ready, else null. Lets a bubble that mounts again show the image on its first render. */
export function peekImageURL(id) {
  return _urlByImageId.get(id) || null
}

/** The one URL an image is shown by (null when the image is not stored). The same URL on every call until deleteImage. */
export function getImageURL(id) {
  const ready = _urlByImageId.get(id)
  if (ready) return Promise.resolve(ready)
  let load = _urlLoadByImageId.get(id)
  if (!load) {
    load = {}
    load.promise = _loadImageURL(id, load)
    _urlLoadByImageId.set(id, load)
  }
  return load.promise
}

export async function deleteImage(id) {
  _forgetURL(id)
  const db = await openDB()
  await new Promise((resolve, reject) => {
    const req = txStore(db, 'readwrite').delete(id)
    req.onsuccess = () => resolve()
    req.onerror = () => reject(req.error)
  })
  // cache から該当 id を引いて size 分減算 (= caps の整合性を保つ)
  if (_capsCache) {
    const idx = _capsCache.recs.findIndex(r => r.id === id)
    if (idx >= 0) {
      _capsCache.total -= _capsCache.recs[idx].size
      _capsCache.count -= 1
      _capsCache.recs.splice(idx, 1)
    }
  }
}

export async function listImageIds() {
  const db = await openDB()
  return new Promise((resolve, reject) => {
    const req = txStore(db, 'readonly').getAllKeys()
    req.onsuccess = () => resolve(req.result || [])
    req.onerror = () => reject(req.error)
  })
}

// activeIds に含まれない ID を全部消す。 messages から imageRefs を集めて呼ぶ想定。
export async function gcImages(activeIds) {
  const active = new Set(activeIds)
  const all = await listImageIds()
  const toDelete = all.filter(id => !active.has(id))
  for (const id of toDelete) {
    try { await deleteImage(id) } catch { /* ignore */ }
  }
  return toDelete.length
}
