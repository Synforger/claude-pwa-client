// @vitest-environment jsdom
//
// path のタップの開き先は 1 か所で決まる: HTML はブラウザの新しいタブ (= スクリプトが動く形)、 folder は木、
// それ以外はプレビュー。 ブラウザで開く時は、 メモを畳む等の後始末を呼ばない。
import { describe, it, expect, vi, afterEach } from 'vitest'
import { openPath } from './openPath.js'
import { getSnapshot, setOverlay } from '../../state/ui.js'

afterEach(() => {
  vi.restoreAllMocks()
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

  it('previews any other file, and runs onLeave first', () => {
    const open = vi.spyOn(window, 'open').mockImplementation(() => null)
    const onLeave = vi.fn()
    openPath('~/notes/plan.md', { onLeave })
    expect(open).not.toHaveBeenCalled()
    expect(onLeave).toHaveBeenCalledTimes(1)
    expect(getSnapshot().overlays.previewPath).toBe('~/notes/plan.md')
  })

  it('opens a folder in the tree', () => {
    openPath('~/pages/deck/')
    expect(getSnapshot().overlays.treeOpen).toBe('~/pages/deck/')
  })
})
