// sw.js の cache 名を build ごとに決める処理の検査。
import { describe, it, expect } from 'vitest'
import { stampServiceWorker, buildIdFor } from './stampServiceWorker.js'

const SW = "const SHELL_CACHE = 'claude-pwa-shell-__BUILD_ID__'\n"

describe('build — stamp the service worker', () => {
  it('replaces the placeholder with a 12-hex build id', () => {
    const { id, source } = stampServiceWorker(SW, ['assets/index-aaa.js'])
    expect(id).toMatch(/^[0-9a-f]{12}$/)
    expect(source).toBe(`const SHELL_CACHE = 'claude-pwa-shell-${id}'\n`)
  })

  it('keeps the name when neither the bundle nor sw.js changed (order does not matter)', () => {
    expect(buildIdFor(SW, ['a.js', 'b.css'])).toBe(buildIdFor(SW, ['b.css', 'a.js']))
  })

  it('changes the name when the bundle changes', () => {
    expect(buildIdFor(SW, ['assets/index-aaa.js'])).not.toBe(buildIdFor(SW, ['assets/index-bbb.js']))
  })

  it('changes the name when sw.js itself changes', () => {
    expect(buildIdFor(SW, ['a.js'])).not.toBe(buildIdFor(`${SW}// fetch strategy changed\n`, ['a.js']))
  })

  it('refuses to ship a worker without the placeholder', () => {
    expect(() => stampServiceWorker("const SHELL_CACHE = 'claude-pwa-shell-v28'\n", ['a.js'])).toThrow(/placeholder/)
  })
})
