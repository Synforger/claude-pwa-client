// お気に入りの一覧は host が持つ (= GET / POST / DELETE /favorites)。 ここで見るのは:
//   - 画面は host の一覧を映す / 足す・外すは先に画面へ出て、 host の答えで確定する
//   - 端末の中に持っていた頃の一覧は、 最初の 1 回で host へ移して消す
import { describe, it, expect, beforeEach, vi } from 'vitest'

const host = { list: [], fail: false, calls: [] }
const entry = (path) => ({ path, name: path.split('/').pop(), is_dir: false })

vi.mock('../../utils/api.js', () => ({
  apiFetch: vi.fn(async (path, options = {}) => {
    const method = options.method || 'GET'
    host.calls.push(`${method} ${path}`)
    if (host.fail) throw new Error('unreachable')
    if (method === 'POST') {
      const { path: p } = JSON.parse(options.body)
      if (!host.list.includes(p)) host.list.push(p)
    }
    if (method === 'DELETE') {
      const p = decodeURIComponent(path.split('path=')[1])
      host.list = host.list.filter(x => x !== p)
    }
    return { ok: true, json: async () => ({ favorites: host.list.map(entry) }) }
  }),
}))

import {
  loadFavs, isFav, addFav, removeFav, toggleFav, subscribeFavs, refreshFavs, _resetFavsForTest,
} from './favorites.js'

const LEGACY_KEY = 'cpc.fileTree.favorites'
const settle = () => new Promise(r => setTimeout(r, 0))

// node 環境には localStorage が無いので、 in-memory の作り物に差し替える
function makeStorage() {
  const m = new Map()
  return {
    getItem: (k) => (m.has(k) ? m.get(k) : null),
    setItem: (k, v) => { m.set(k, String(v)) },
    removeItem: (k) => { m.delete(k) },
  }
}

beforeEach(() => {
  host.list = []
  host.fail = false
  host.calls = []
  vi.stubGlobal('localStorage', makeStorage())
  _resetFavsForTest()
})

describe('favorites', () => {
  it('shows the list the host holds', async () => {
    host.list = ['/home/u/a.md', '/home/u/docs']
    await refreshFavs()
    expect(loadFavs().map(f => f.path)).toEqual(['/home/u/a.md', '/home/u/docs'])
    expect(isFav('/home/u/docs')).toBe(true)
    expect(isFav('/home/u/other')).toBe(false)
  })

  it('takes the list again when a view opens, and tells it', async () => {
    host.list = ['/home/u/a.md']
    const seen = []
    const stop = subscribeFavs(list => seen.push(list.map(f => f.path)))
    await settle()
    expect(seen).toEqual([['/home/u/a.md']])
    stop()
    host.list = ['/home/u/a.md', '/home/u/b.md'] // a line appended to the file from elsewhere
    await refreshFavs()
    expect(seen).toHaveLength(1) // no longer subscribed
    expect(loadFavs()).toHaveLength(2)
  })

  it('shows an added entry at once and settles on the answer of the host', async () => {
    await refreshFavs()
    const shown = addFav('/home/u/a.md', false, 'a.md')
    expect(shown.map(f => f.path)).toEqual(['/home/u/a.md'])
    expect(isFav('/home/u/a.md')).toBe(true)
    await settle()
    expect(host.list).toEqual(['/home/u/a.md'])
    expect(loadFavs()).toEqual([entry('/home/u/a.md')])
  })

  it('removes an entry on the host', async () => {
    host.list = ['/home/u/a.md', '/home/u/b c.md']
    await refreshFavs()
    expect(removeFav('/home/u/b c.md').map(f => f.path)).toEqual(['/home/u/a.md'])
    await settle()
    expect(host.list).toEqual(['/home/u/a.md'])
    expect(host.calls).toContain('DELETE /favorites?path=%2Fhome%2Fu%2Fb%20c.md')
  })

  it('toggles', async () => {
    await refreshFavs()
    toggleFav('/home/u/a.md', false, 'a.md')
    expect(isFav('/home/u/a.md')).toBe(true)
    toggleFav('/home/u/a.md', false, 'a.md')
    expect(isFav('/home/u/a.md')).toBe(false)
    await settle()
    expect(host.list).toEqual([])
  })

  it('keeps quick changes in order, without an earlier answer undoing a later change', async () => {
    await refreshFavs()
    const seen = []
    subscribeFavs(list => seen.push(list.map(f => f.path).join(',')))
    addFav('/home/u/a.md', false, 'a.md')
    addFav('/home/u/b.md', false, 'b.md')
    await settle()
    await settle()
    expect(host.list).toEqual(['/home/u/a.md', '/home/u/b.md'])
    // b never disappears between the two answers
    expect(seen.filter(s => s === '/home/u/a.md')).toHaveLength(1)
    expect(seen.at(-1)).toBe('/home/u/a.md,/home/u/b.md')
  })

  it('goes back to what the host holds when a change does not get through', async () => {
    host.list = ['/home/u/a.md']
    await refreshFavs()
    host.fail = true
    addFav('/home/u/b.md', false, 'b.md')
    expect(isFav('/home/u/b.md')).toBe(true)
    await settle()
    host.fail = false
    await refreshFavs()
    expect(loadFavs().map(f => f.path)).toEqual(['/home/u/a.md'])
  })

  it('carries the list this browser kept over to the host once, then drops the local copy', async () => {
    host.list = ['/home/u/on-host.md']
    localStorage.setItem(LEGACY_KEY, JSON.stringify([
      { path: '/home/u/on-device.md', name: 'on-device.md', is_dir: false },
      { path: '/home/u/on-host.md', name: 'on-host.md' },
      { nonsense: true },
    ]))
    await refreshFavs()
    expect(host.list).toEqual(['/home/u/on-host.md', '/home/u/on-device.md'])
    expect(loadFavs().map(f => f.path)).toEqual(['/home/u/on-host.md', '/home/u/on-device.md'])
    expect(localStorage.getItem(LEGACY_KEY)).toBeNull()
    const posts = host.calls.filter(c => c.startsWith('POST')).length
    await refreshFavs()
    expect(host.calls.filter(c => c.startsWith('POST')).length).toBe(posts)
  })

  it('keeps the local copy while the host cannot be reached, and carries it over later', async () => {
    localStorage.setItem(LEGACY_KEY, JSON.stringify([{ path: '/home/u/on-device.md' }]))
    host.fail = true
    await refreshFavs()
    expect(localStorage.getItem(LEGACY_KEY)).not.toBeNull()
    host.fail = false
    await refreshFavs()
    expect(host.list).toEqual(['/home/u/on-device.md'])
    expect(localStorage.getItem(LEGACY_KEY)).toBeNull()
  })
})
