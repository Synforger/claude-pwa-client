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

// `replacing`: another worker was active when this one was installed. `screens`: what `clients.matchAll` returns.
function loadSw({ replacing = false, screens = [] } = {}) {
  const listeners = {}
  const puts = []
  const fetched = []
  const logs = []
  const delays = []
  const cache = { put: (key) => { puts.push(typeof key === 'string' ? key : key.url); return Promise.resolve() } }
  const context = {
    self: {
      location: { origin: ORIGIN },
      addEventListener: (type, fn) => { listeners[type] = fn },
      skipWaiting: () => Promise.resolve(),
      clients: { claim: () => Promise.resolve(), matchAll: () => Promise.resolve(screens) },
      registration: { active: replacing ? {} : null },
    },
    // Runs the wait at once and keeps what was asked for
    setTimeout: (fn, ms) => { delays.push(ms); fn(); return 0 },
    caches: {
      open: () => Promise.resolve(cache),
      match: () => Promise.resolve(undefined),
      keys: () => Promise.resolve([]),
      delete: () => Promise.resolve(true),
    },
    fetch: (request, init) => {
      fetched.push(request)
      if (request === '/log/sw') logs.push(JSON.parse(init.body))
      return Promise.resolve({ ok: true, clone() { return this } })
    },
    // Copies the request and lays the init over it, as `new Request(request, init)` does
    Request: class { constructor(input, init = {}) { Object.assign(this, input, init) } },
    URL,
    console,
  }
  vm.runInNewContext(SW_SOURCE, context)
  return { listeners, puts, fetched, delays, logs }
}

// fetch listener に 1 件流し、 respondWith された応答の処理 (= cache 保存) が終わるまで待つ。
async function dispatch(sw, { pathname, mode = 'no-cors', destination = '', cache = 'default' }) {
  let responded = null
  const event = {
    request: { method: 'GET', url: `${ORIGIN}${pathname}`, mode, destination, cache },
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

  it('takes the entry page from the network even when the browser asks for a cached copy', async () => {
    const r = await dispatch(sw, { pathname: '/', mode: 'navigate', destination: 'document', cache: 'force-cache' })
    expect(r.responded).toBe(true)
    expect(sw.fetched).toHaveLength(1)
    expect(sw.fetched[0].url).toBe(`${ORIGIN}/`)
    expect(sw.fetched[0].cache).toBe('no-store')
  })

  it('leaves an iframe navigation alone (= it is not the app shell)', async () => {
    const r = await dispatch(sw, { pathname: '/some/page', mode: 'navigate', destination: 'iframe' })
    expect(r.responded).toBe(false)
    expect(sw.puts).toEqual([])
  })

  it.each([
    ['/moonlight/', 'navigate', 'iframe'],
    ['/moonlight/stream.html', 'navigate', 'document'],
    ['/ext/notes/', 'navigate', 'iframe'],
    ['/ext/notes/', 'navigate', 'document'],
    ['/ext/notes/icon.svg', 'no-cors', 'image'],
    ['/moonlight/logo.png', 'no-cors', 'image'],
    ['/file/view/home/me/pages/deck/index.html', 'navigate', 'document'],
    ['/file/view/home/me/pages/deck/cam/a.png', 'no-cors', 'image'],
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


// A screen as `clients.matchAll` gives it: it can be told to navigate, and says what kind of frame it is.
function screenAt(id, pathname, { frameType = 'top-level', fails = false } = {}) {
  const navigated = []
  return {
    id,
    url: `${ORIGIN}${pathname}`,
    frameType,
    navigated,
    navigate: (url) => { navigated.push(url); return fails ? Promise.reject(new Error('refused')) : Promise.resolve({}) },
  }
}

// Runs install, then activate, the way the browser does for a new worker.
async function install(sw) {
  let installing = null
  sw.listeners.install({ waitUntil: (p) => { installing = p } })
  await installing
}
async function activate(sw) {
  let activating = null
  sw.listeners.activate({ waitUntil: (p) => { activating = p } })
  await activating
}
function announce(sw, id) {
  sw.listeners.message({ data: { type: 'self-updating', build: 'b' }, source: { id } })
}

describe('sw.js moves the screens that cannot move themselves, when a new worker takes over', () => {
  it('reloads a screen that did not announce, onto its own address, and records it', async () => {
    const old = screenAt('c1', '/?ses=ses_a')
    const sw = loadSw({ replacing: true, screens: [old] })
    await install(sw)
    await activate(sw)
    expect(old.navigated).toEqual([`${ORIGIN}/?ses=ses_a`])
    expect(sw.logs).toEqual([{ stage: 'update:sw-navigate', moved: ['/'], announced: 0, controlled: 1 }])
  })

  it('waits before it moves anything, so a screen has time to announce', async () => {
    const sw = loadSw({ replacing: true, screens: [] })
    await install(sw)
    await activate(sw)
    expect(sw.delays).toEqual([3000])
  })

  it('leaves a screen that announced itself alone, and reloads the one that did not', async () => {
    const modern = screenAt('c1', '/')
    const old = screenAt('c2', '/')
    const sw = loadSw({ replacing: true, screens: [modern, old] })
    await install(sw)
    announce(sw, 'c1')
    await activate(sw)
    expect(modern.navigated).toEqual([])
    expect(old.navigated).toHaveLength(1)
  })

  it('reloads nothing for a first registration (= no worker was active before)', async () => {
    const found = screenAt('c1', '/')
    const sw = loadSw({ replacing: false, screens: [found] })
    await install(sw)
    await activate(sw)
    expect(found.navigated).toEqual([])
    expect(sw.delays).toEqual([])
    expect(sw.logs).toEqual([])
  })

  it('leaves frames and the embedded apps alone', async () => {
    const frame = screenAt('c1', '/', { frameType: 'nested' })
    const embedded = [screenAt('c2', '/ext/fixture/'), screenAt('c3', '/moonlight/'), screenAt('c4', '/file/page.html')]
    const sw = loadSw({ replacing: true, screens: [frame, ...embedded] })
    await install(sw)
    await activate(sw)
    expect([frame, ...embedded].flatMap((screen) => screen.navigated)).toEqual([])
    expect(sw.logs).toEqual([])
  })

  it('keeps going when one screen refuses, and records what it started and what failed', async () => {
    const refuses = screenAt('c1', '/a', { fails: true })
    const fine = screenAt('c2', '/b')
    const sw = loadSw({ replacing: true, screens: [refuses, fine] })
    await install(sw)
    await activate(sw)
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(fine.navigated).toHaveLength(1)
    expect(sw.logs).toEqual([
      { stage: 'update:sw-navigate', moved: ['/a', '/b'], announced: 0, controlled: 2 },
      { stage: 'update:sw-navigate-failed', path: '/a' },
    ])
  })

  it('does not wait for a reload to finish: the browser answers it through this worker once it has activated', async () => {
    const slow = screenAt('c1', '/')
    slow.navigate = () => new Promise(() => {})
    const sw = loadSw({ replacing: true, screens: [slow] })
    await install(sw)
    await activate(sw)
  })
})
