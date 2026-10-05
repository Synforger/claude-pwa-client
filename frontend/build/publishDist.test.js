import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { existsSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { publishDist } from './publishDist.js'

let root
const dist = () => join(root, 'dist')
const next = () => join(root, 'dist.next')

// 1 つの build を dist.next に作る: 入口の頁は自分の assets を名前で指す
function writeBuild(tag, extraTop = {}) {
  const dir = next()
  mkdirSync(join(dir, 'assets'), { recursive: true })
  writeFileSync(join(dir, 'assets', `index-${tag}.js`), `console.log("${tag}")`)
  writeFileSync(join(dir, 'assets', `Drawer-${tag}.js`), `export default "${tag}"`)
  writeFileSync(join(dir, 'index.html'), `<script type="module" src="/assets/index-${tag}.js"></script>`)
  writeFileSync(join(dir, 'sw.js'), `const SHELL_CACHE = 'shell-${tag}'`)
  writeFileSync(join(dir, 'manifest.json'), `{"name":"${tag}"}`)
  for (const [name, body] of Object.entries(extraTop)) writeFileSync(join(dir, name), body)
}

const assets = () => readdirSync(join(dist(), 'assets')).sort()
const read = (f) => readFileSync(join(dist(), f), 'utf-8')

beforeEach(() => { root = mkdtempSync(join(tmpdir(), 'publish-dist-')) })
afterEach(() => { rmSync(root, { recursive: true, force: true }) })

describe('publishDist', () => {
  it('publishes the first build into an empty place', () => {
    writeBuild('aaa')
    publishDist(next(), dist())
    expect(assets()).toEqual(['Drawer-aaa.js', 'index-aaa.js'])
    expect(read('index.html')).toContain('index-aaa.js')
    expect(existsSync(next())).toBe(false)
  })

  it('keeps the files of the build it replaces, so a screen still on that build can load its parts', () => {
    writeBuild('aaa'); publishDist(next(), dist())
    writeBuild('bbb'); publishDist(next(), dist())
    expect(assets()).toEqual(['Drawer-aaa.js', 'Drawer-bbb.js', 'index-aaa.js', 'index-bbb.js'])
    expect(read('index.html')).toContain('index-bbb.js')
    expect(read('sw.js')).toContain('shell-bbb')
    expect(read('manifest.json')).toContain('bbb')
  })

  it('drops the files of builds older than the one it replaces', () => {
    writeBuild('aaa'); publishDist(next(), dist())
    writeBuild('bbb'); publishDist(next(), dist())
    writeBuild('ccc'); const result = publishDist(next(), dist())
    expect(assets()).toEqual(['Drawer-bbb.js', 'Drawer-ccc.js', 'index-bbb.js', 'index-ccc.js'])
    expect(result).toEqual({ added: 2, removed: 2 })
  })

  it('never shows an entry page whose files are missing, at any step', () => {
    writeBuild('aaa'); publishDist(next(), dist())
    writeBuild('bbb')
    // 載せ替えの最中のどこで止まっても、 入口の頁が指す file は在る:
    // 新しい assets を足した直後 (= 入口はまだ古い) を作って確かめる
    mkdirSync(join(dist(), 'assets'), { recursive: true })
    const pointsAtExisting = () => {
      const src = /src="\/(assets\/[^"]+)"/.exec(read('index.html'))[1]
      return existsSync(join(dist(), src))
    }
    expect(pointsAtExisting()).toBe(true)
    publishDist(next(), dist())
    expect(pointsAtExisting()).toBe(true)
    // 古い入口が指していた file も残っている (= 入口を読んだ直後に載せ替わった画面も壊れない)
    expect(existsSync(join(dist(), 'assets', 'index-aaa.js'))).toBe(true)
  })

  it('republishing the same build changes nothing', () => {
    writeBuild('aaa'); publishDist(next(), dist())
    writeBuild('bbb'); publishDist(next(), dist())
    writeBuild('bbb'); const result = publishDist(next(), dist())
    expect(result).toEqual({ added: 0, removed: 0 })
    expect(assets()).toEqual(['Drawer-aaa.js', 'Drawer-bbb.js', 'index-aaa.js', 'index-bbb.js'])
  })

  it('removes a top-level file the new build no longer has', () => {
    writeBuild('aaa', { 'old-icon.svg': '<svg/>' }); publishDist(next(), dist())
    writeBuild('bbb'); publishDist(next(), dist())
    expect(existsSync(join(dist(), 'old-icon.svg'))).toBe(false)
  })

  it('treats what is already served as the previous build when there is no record yet', () => {
    // 載せ替えの仕組みを入れる前に作られた dist (= 記録が無い) へ、 初めて載せる時
    mkdirSync(join(dist(), 'assets'), { recursive: true })
    writeFileSync(join(dist(), 'assets', 'index-old.js'), 'old')
    writeFileSync(join(dist(), 'index.html'), '<script type="module" src="/assets/index-old.js"></script>')
    writeBuild('new'); publishDist(next(), dist())
    expect(assets()).toEqual(['Drawer-new.js', 'index-new.js', 'index-old.js'])
  })

  it('refuses to publish when there is no build', () => {
    expect(() => publishDist(next(), dist())).toThrow(/no build to publish/)
  })

  it('leaves no half-written file behind', () => {
    writeBuild('aaa'); publishDist(next(), dist())
    const all = readdirSync(dist(), { recursive: true }).map(String)
    expect(all.filter((f) => f.endsWith('.publishing'))).toEqual([])
  })
})
