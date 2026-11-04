// @vitest-environment jsdom
//
// path のタップの開き先は 1 か所で決まる: HTML だけがブラウザの新しい窓 (= OS の既定のブラウザ。 スクリプトが動く形)、
// folder は木、 それ以外 (= 資料の pdf・Office・tif、 画像、 Markdown) は client の中のプレビュー。 既定のブラウザで開く時は、
// メモを畳む等の後始末を呼ばない。 iPhone のホーム画面の PWA は、 HTML を Safari へ渡す (= _common/externalBrowser.js)。
import { describe, it, expect, vi, afterEach } from 'vitest'
import { openLinkedPath, openPath } from '../../../src/features/file-preview/openPath.js'
import { getSnapshot, setOverlay } from '../../../src/state/ui.js'

const IPHONE_UA = 'Mozilla/5.0 (iPhone; CPU iPhone OS 26_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148'

// ホーム画面から開いた形 (= display-mode: standalone、 navigator.standalone) の iPhone にする
function asIphoneHomeScreen() {
  vi.spyOn(window.navigator, 'userAgent', 'get').mockReturnValue(IPHONE_UA)
  window.matchMedia = vi.fn(query => ({ matches: query === '(display-mode: standalone)', media: query }))
  Object.defineProperty(window.navigator, 'standalone', { value: true, configurable: true })
}

afterEach(() => {
  vi.restoreAllMocks()
  delete window.matchMedia
  delete window.Capacitor
  delete window.navigator.standalone
  setOverlay('previewPath', null)
  setOverlay('treeOpen', null)
})

describe('openPath', () => {
  it('opens an HTML file in a new browser window through /file/open, and leaves the overlays alone', () => {
    const open = vi.spyOn(window, 'open').mockImplementation(() => null)
    const onLeave = vi.fn()
    openPath('~/pages/deck/index.html', { onLeave })
    expect(open).toHaveBeenCalledTimes(1)
    const [url, target] = open.mock.calls[0]
    expect(url).toMatch(/\/file\/open\?path=~%2Fpages%2Fdeck%2Findex\.html$/)
    expect(target).toBe('_blank')
    expect(onLeave).not.toHaveBeenCalled()
    expect(getSnapshot().overlays.previewPath ?? null).toBe(null)
  })

  it('treats .htm and upper case the same', () => {
    const open = vi.spyOn(window, 'open').mockImplementation(() => null)
    openPath('/srv/pages/REPORT.HTML')
    openPath('/srv/pages/old.htm')
    expect(open).toHaveBeenCalledTimes(2)
  })

  it.each([
    '~/materials/spec.pdf',
    '/srv/deck.PPTX',
    '/srv/sheet.xlsx',
    '/srv/memo.docx',
    '/srv/scan.tif',
    '/srv/scan.TIFF',
  ])('previews the document %s inside the client, never in a browser window', path => {
    const open = vi.spyOn(window, 'open').mockImplementation(() => null)
    const onLeave = vi.fn()
    openPath(path, { onLeave })
    expect(open).not.toHaveBeenCalled()
    expect(onLeave).toHaveBeenCalledTimes(1)
    expect(getSnapshot().overlays.previewPath).toBe(path)
  })

  it.each(['~/pictures/photo.png', '/srv/shot.JPG', '/srv/anim.gif'])('previews the image %s inside the client', path => {
    const open = vi.spyOn(window, 'open').mockImplementation(() => null)
    openPath(path)
    expect(open).not.toHaveBeenCalled()
    expect(getSnapshot().overlays.previewPath).toBe(path)
  })

  it('does not take a name that only contains a document extension', () => {
    const open = vi.spyOn(window, 'open').mockImplementation(() => null)
    openPath('~/notes/spec.pdf.md')
    openPath('~/notes/pdf')
    expect(open).not.toHaveBeenCalled()
    expect(getSnapshot().overlays.previewPath).toBe('~/notes/pdf')
  })

  it('previews Markdown, and runs onLeave first', () => {
    const open = vi.spyOn(window, 'open').mockImplementation(() => null)
    const onLeave = vi.fn()
    openPath('~/notes/plan.md', { onLeave })
    expect(open).not.toHaveBeenCalled()
    expect(onLeave).toHaveBeenCalledTimes(1)
    expect(getSnapshot().overlays.previewPath).toBe('~/notes/plan.md')
  })

  it('hands an HTML file to Safari on the iPhone home screen, and does not open the preview', () => {
    asIphoneHomeScreen()
    const open = vi.spyOn(window, 'open').mockImplementation(() => null)
    const href = vi.fn()
    vi.spyOn(window, 'location', 'get').mockReturnValue({
      get href() { return 'http://localhost:3000/' },
      set href(value) { href(value) },
    })
    const onLeave = vi.fn()
    openPath('~/pages/deck/index.html', { onLeave })
    expect(open).not.toHaveBeenCalled()
    expect(href).toHaveBeenCalledTimes(1)
    expect(href.mock.calls[0][0]).toMatch(/^x-safari-http:\/\/localhost:\d+\/file\/open\?path=~%2Fpages%2Fdeck%2Findex\.html$/)
    expect(onLeave).not.toHaveBeenCalled()
    expect(getSnapshot().overlays.previewPath ?? null).toBe(null)
  })

  it('previews a document on the iPhone home screen like anywhere else', () => {
    asIphoneHomeScreen()
    const open = vi.spyOn(window, 'open').mockImplementation(() => null)
    openPath('~/materials/spec.pdf')
    expect(open).not.toHaveBeenCalled()
    expect(getSnapshot().overlays.previewPath).toBe('~/materials/spec.pdf')
  })

  it('hands an HTML file to the iPhone app as a new window, which the app passes to the default browser', () => {
    // PageSheetPlugin が /file/open の HTML の窓を既定のブラウザへ渡す。 app の画面を置き換える経路
    // (= location の書き換え) は使わない
    asIphoneHomeScreen()
    window.Capacitor = { isNativePlatform: () => true }
    const open = vi.spyOn(window, 'open').mockImplementation(() => null)
    const assign = vi.fn()
    vi.spyOn(window, 'location', 'get').mockReturnValue({ ...window.location, assign })
    openPath('~/pages/deck/index.html')
    expect(open).toHaveBeenCalledTimes(1)
    expect(open.mock.calls[0][0]).toMatch(/\/file\/open\?path=~%2Fpages%2Fdeck%2Findex\.html$/)
    expect(open.mock.calls[0][1]).toBe('_blank')
    expect(assign).not.toHaveBeenCalled()
    expect(getSnapshot().overlays.previewPath ?? null).toBe(null)
  })

  it('previews a document in the iPhone app too, without a new window', () => {
    window.Capacitor = { isNativePlatform: () => true }
    const open = vi.spyOn(window, 'open').mockImplementation(() => null)
    openPath('~/materials/spec.pdf')
    expect(open).not.toHaveBeenCalled()
    expect(getSnapshot().overlays.previewPath).toBe('~/materials/spec.pdf')
  })

  it('opens a folder in the tree', () => {
    openPath('~/pages/deck/')
    expect(getSnapshot().overlays.treeOpen).toBe('~/pages/deck/')
  })
})

describe('openLinkedPath', () => {
  // The backend's answer to `POST /file/os-open`
  function backendAnswers(opened) {
    const fetch = vi.fn(async () => new Response(JSON.stringify({ opened }), { status: 200 }))
    vi.stubGlobal('fetch', fetch)
    return fetch
  }

  afterEach(() => vi.unstubAllGlobals())

  it.each(['~/Movies/session', '~/tools/run.py', '~/materials/spec.pdf', '~/pictures/photo.png'])(
    'hands %s to the backend on a computer, and leaves the screen as it was', async path => {
      const fetch = backendAnswers(true)
      const onLeave = vi.fn()
      await openLinkedPath(path, { onLeave })
      expect(fetch).toHaveBeenCalledTimes(1)
      const [url, options] = fetch.mock.calls[0]
      expect(url).toMatch(/\/file\/os-open$/)
      expect(options.method).toBe('POST')
      expect(JSON.parse(options.body)).toEqual({ path })
      expect(onLeave).not.toHaveBeenCalled()
      expect(getSnapshot().overlays.treeOpen ?? null).toBe(null)
      expect(getSnapshot().overlays.previewPath ?? null).toBe(null)
    })

  it.each(['~/notes/plan.md', '~/notes/README.MARKDOWN'])('keeps Markdown %s in the preview without asking', async path => {
    const fetch = backendAnswers(true)
    await openLinkedPath(path)
    expect(fetch).not.toHaveBeenCalled()
    expect(getSnapshot().overlays.previewPath).toBe(path)
  })

  it('opens the path as before when the backend did not open it', async () => {
    backendAnswers(false)
    const onLeave = vi.fn()
    await openLinkedPath('~/materials/spec.pdf', { onLeave })
    expect(onLeave).toHaveBeenCalledTimes(1)
    expect(getSnapshot().overlays.previewPath).toBe('~/materials/spec.pdf')
  })

  it('opens the tree when the backend is not a Mac', async () => {
    backendAnswers(false)
    await openLinkedPath('~/pages/deck/')
    expect(getSnapshot().overlays.treeOpen).toBe('~/pages/deck/')
  })

  it('opens the path as before when the backend cannot be reached', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('offline') }))
    await openLinkedPath('~/materials/spec.pdf')
    expect(getSnapshot().overlays.previewPath).toBe('~/materials/spec.pdf')
  })

  it('opens HTML within the tap: nothing is awaited before the new window', () => {
    const fetch = backendAnswers(true)
    const open = vi.spyOn(window, 'open').mockImplementation(() => null)
    openLinkedPath('~/pages/deck/index.html')
    expect(open).toHaveBeenCalledTimes(1)
    expect(fetch).not.toHaveBeenCalled()
  })

  it('keeps everything in the client on an iPhone, without asking the backend', async () => {
    const fetch = backendAnswers(true)
    vi.spyOn(window.navigator, 'userAgent', 'get').mockReturnValue(IPHONE_UA)
    await openLinkedPath('~/pages/deck/')
    expect(getSnapshot().overlays.treeOpen).toBe('~/pages/deck/')
    await openLinkedPath('~/materials/spec.pdf')
    expect(getSnapshot().overlays.previewPath).toBe('~/materials/spec.pdf')
    expect(fetch).not.toHaveBeenCalled()
  })
})
