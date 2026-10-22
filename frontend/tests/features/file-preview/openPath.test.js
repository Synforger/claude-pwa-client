// @vitest-environment jsdom
//
// path のタップの開き先は 1 か所で決まる: HTML だけがブラウザの新しい窓 (= OS の既定のブラウザ。 スクリプトが動く形)、
// folder は木、 それ以外 (= 資料の pdf・Office・tif、 画像、 Markdown) は client の中のプレビュー。 既定のブラウザで開く時は、
// メモを畳む等の後始末を呼ばない。 iPhone のホーム画面の PWA は、 新しい窓を開くと戻れないので、 HTML もプレビューの枠で開く。
import { describe, it, expect, vi, afterEach } from 'vitest'
import { openPath } from '../../../src/features/file-preview/openPath.js'
import { getSnapshot, setOverlay } from '../../../src/state/ui.js'

const IPHONE_UA = 'Mozilla/5.0 (iPhone; CPU iPhone OS 26_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148'

// ホーム画面から開いた形 (= display-mode: standalone) の iPhone にする
function asIphoneHomeScreen() {
  vi.spyOn(window.navigator, 'userAgent', 'get').mockReturnValue(IPHONE_UA)
  window.matchMedia = vi.fn(query => ({ matches: query === '(display-mode: standalone)', media: query }))
}

afterEach(() => {
  vi.restoreAllMocks()
  delete window.matchMedia
  delete window.Capacitor
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

  it('opens an HTML file in the preview on the iPhone home screen, where a new window leaves no way back', () => {
    asIphoneHomeScreen()
    const open = vi.spyOn(window, 'open').mockImplementation(() => null)
    const onLeave = vi.fn()
    openPath('~/pages/deck/index.html', { onLeave })
    expect(open).not.toHaveBeenCalled()
    expect(onLeave).toHaveBeenCalledTimes(1)
    expect(getSnapshot().overlays.previewPath).toBe('~/pages/deck/index.html')
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
