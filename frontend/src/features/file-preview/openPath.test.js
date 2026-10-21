// @vitest-environment jsdom
//
// path のタップの開き先は 1 か所で決まる: HTML と資料 (= pdf・Office・tif) はブラウザの新しいタブ (= スクリプトが動く形)、
// folder は木、 それ以外 (= Markdown を含む) はプレビュー。 ブラウザで開く時は、 メモを畳む等の後始末を呼ばない。 iPhone のホーム画面の PWA は、
// 新しいタブを開くと戻れないので、 HTML もプレビューの枠で開く。
import { describe, it, expect, vi, afterEach } from 'vitest'
import { openPath } from './openPath.js'
import { getSnapshot, setOverlay } from '../../state/ui.js'

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
  it('opens an HTML file in a new browser tab through /file/open, and leaves the overlays alone', () => {
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
  ])('opens the document %s in a new browser tab through /file/open', path => {
    const open = vi.spyOn(window, 'open').mockImplementation(() => null)
    const onLeave = vi.fn()
    openPath(path, { onLeave })
    expect(open).toHaveBeenCalledTimes(1)
    expect(open.mock.calls[0][0].endsWith(`/file/open?path=${encodeURIComponent(path)}`)).toBe(true)
    expect(open.mock.calls[0][1]).toBe('_blank')
    expect(onLeave).not.toHaveBeenCalled()
    expect(getSnapshot().overlays.previewPath ?? null).toBe(null)
  })

  it('does not take a name that only contains a document extension', () => {
    const open = vi.spyOn(window, 'open').mockImplementation(() => null)
    openPath('~/notes/spec.pdf.md')
    openPath('~/notes/pdf')
    expect(open).not.toHaveBeenCalled()
    expect(getSnapshot().overlays.previewPath).toBe('~/notes/pdf')
  })

  it('previews any other file, and runs onLeave first', () => {
    const open = vi.spyOn(window, 'open').mockImplementation(() => null)
    const onLeave = vi.fn()
    openPath('~/notes/plan.md', { onLeave })
    expect(open).not.toHaveBeenCalled()
    expect(onLeave).toHaveBeenCalledTimes(1)
    expect(getSnapshot().overlays.previewPath).toBe('~/notes/plan.md')
  })

  it('opens an HTML file in the preview on the iPhone home screen, where a new tab leaves no way back', () => {
    asIphoneHomeScreen()
    const open = vi.spyOn(window, 'open').mockImplementation(() => null)
    const onLeave = vi.fn()
    openPath('~/pages/deck/index.html', { onLeave })
    expect(open).not.toHaveBeenCalled()
    expect(onLeave).toHaveBeenCalledTimes(1)
    expect(getSnapshot().overlays.previewPath).toBe('~/pages/deck/index.html')
  })

  it('opens a document in the preview frame on the iPhone home screen too', () => {
    asIphoneHomeScreen()
    const open = vi.spyOn(window, 'open').mockImplementation(() => null)
    openPath('~/materials/spec.pdf')
    expect(open).not.toHaveBeenCalled()
    expect(getSnapshot().overlays.previewPath).toBe('~/materials/spec.pdf')
  })

  it('keeps the new tab in the iPhone app, whose page sheet has a close button', () => {
    asIphoneHomeScreen()
    window.Capacitor = { isNativePlatform: () => true }
    const open = vi.spyOn(window, 'open').mockImplementation(() => null)
    openPath('~/pages/deck/index.html')
    expect(open).toHaveBeenCalledTimes(1)
    expect(getSnapshot().overlays.previewPath ?? null).toBe(null)
  })

  it.each([
    '~/pages/deck/index.html',
    '~/materials/spec.pdf',
    '/srv/deck.pptx',
    '/srv/scan.tif',
  ])('hands %s to the app\'s page sheet (a new window), never to the app screen itself', path => {
    // iPhone の app は新しい窓を、 「完了」 で閉じる閲覧の画面で開く (= PageSheetPlugin)。 app の画面を置き換える
    // 経路 (= location の書き換え) は使わない
    window.Capacitor = { isNativePlatform: () => true }
    const open = vi.spyOn(window, 'open').mockImplementation(() => null)
    const assign = vi.fn()
    vi.spyOn(window, 'location', 'get').mockReturnValue({ ...window.location, assign })
    openPath(path)
    expect(open).toHaveBeenCalledTimes(1)
    expect(open.mock.calls[0][1]).toBe('_blank')
    expect(assign).not.toHaveBeenCalled()
  })

  it('opens a folder in the tree', () => {
    openPath('~/pages/deck/')
    expect(getSnapshot().overlays.treeOpen).toBe('~/pages/deck/')
  })
})
