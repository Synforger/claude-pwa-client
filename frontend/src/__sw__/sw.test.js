// public/sw.js の fetch 戦略の検査。 SW は bundle に入らない素の script なので、 fake の
// `self` / `caches` / `fetch` を与えた vm 上で読み込み、 登録された fetch listener を直接叩く。
// 見るのは「どの request に respondWith したか」 と「何を cache に保存したか」 の 2 点だけ。
import { describe, it, expect, beforeEach } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'
import vm from 'node:vm'
import { fileURLToPath } from 'node:url'

const here = path.dirname(fileURLToPath(import.meta.url))
const SW_SOURCE = fs.readFileSync(path.join(here, '../../public/sw.js'), 'utf-8')
const ORIGIN = 'https://host.example'

function loadSw() {
  const listeners = {}
  const puts = []
  const cache = { put: (key) => { puts.push(typeof key === 'string' ? key : key.url); return Promise.resolve() } }
  const context = {
    self: {
      location: { origin: ORIGIN },
      addEventListener: (type, fn) => { listeners[type] = fn },
      skipWaiting: () => Promise.resolve(),
      clients: { claim: () => Promise.resolve(), matchAll: () => Promise.resolve([]) },
      registration: {},
    },
    caches: {
      open: () => Promise.resolve(cache),
      match: () => Promise.resolve(undefined),
      keys: () => Promise.resolve([]),
      delete: () => Promise.resolve(true),
    },
    fetch: () => Promise.resolve({ ok: true, clone() { return this } }),
    URL,
    console,
  }
  vm.runInNewContext(SW_SOURCE, context)
  return { listeners, puts }
}

// fetch listener に 1 件流し、 respondWith された応答の処理 (= cache 保存) が終わるまで待つ。
async function dispatch(sw, { pathname, mode = 'no-cors', destination = '' }) {
  let responded = null
  const event = {
    request: { method: 'GET', url: `${ORIGIN}${pathname}`, mode, destination },
    respondWith: (p) => { responded = p },
  }
  sw.listeners.fetch(event)
  if (responded) await responded
  return { responded: responded !== null }
}

describe('sw.js fetch strategy', () => {
  let sw
  beforeEach(() => { sw = loadSw() })

  it('stores a top-level navigation under the single "/" key', async () => {
    const r = await dispatch(sw, { pathname: '/?ses=abc', mode: 'navigate', destination: 'document' })
    expect(r.responded).toBe(true)
    expect(sw.puts).toEqual(['/'])
  })

  it('leaves an iframe navigation alone (= it is not the app shell)', async () => {
    const r = await dispatch(sw, { pathname: '/some/page', mode: 'navigate', destination: 'iframe' })
    expect(r.responded).toBe(false)
    expect(sw.puts).toEqual([])
  })

  it.each([
    ['/moonlight/', 'navigate', 'iframe'],
    ['/moonlight/stream.html', 'navigate', 'document'],
    ['/ext/reaper/', 'navigate', 'iframe'],
    ['/ext/reaper/', 'navigate', 'document'],
    ['/ext/reaper/icon.svg', 'no-cors', 'image'],
    ['/moonlight/logo.png', 'no-cors', 'image'],
  ])('never intercepts embedded app %s (%s / %s)', async (pathname, mode, destination) => {
    const r = await dispatch(sw, { pathname, mode, destination })
    expect(r.responded).toBe(false)
    expect(sw.puts).toEqual([])
  })

  it('still caches the app shell assets', async () => {
    const r = await dispatch(sw, { pathname: '/icon-192.svg', destination: 'image' })
    expect(r.responded).toBe(true)
    expect(sw.puts).toEqual([`${ORIGIN}/icon-192.svg`])
  })

  it('does not intercept API requests', async () => {
    const r = await dispatch(sw, { pathname: '/sessions', destination: '' })
    expect(r.responded).toBe(false)
  })
})
