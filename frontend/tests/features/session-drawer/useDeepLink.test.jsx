// @vitest-environment jsdom
//
// useDeepLink: 画面を開いた URL の印 (= ?ses= / ?preview=) を読んで、 タブを切り替える・file のプレビューを開く。
// 印は一度読んだら URL から消す (= 読み込み直しで同じプレビューが開き直さない)。
import { describe, it, expect, vi, afterEach } from 'vitest'
import { renderHook } from '@testing-library/react'
import { useDeepLink } from '../../../src/features/session-drawer/useDeepLink.js'
import { getSnapshot, setOverlay } from '../../../src/state/ui.js'

function openAt(search) {
  window.history.replaceState({}, '', `/${search}`)
}

afterEach(() => {
  setOverlay('previewPath', null)
  openAt('')
})

describe('useDeepLink', () => {
  it('opens the file of ?preview= in the preview, and removes the mark from the URL', () => {
    openAt('?preview=~%2Fnotes%2Fmemo.md')
    const setActiveId = vi.fn()
    renderHook(() => useDeepLink(setActiveId))
    expect(getSnapshot().overlays.previewPath).toBe('~/notes/memo.md')
    expect(setActiveId).not.toHaveBeenCalled()
    expect(window.location.search).toBe('')
  })

  it('switches to the tab of ?ses=, and leaves the preview closed', () => {
    openAt('?ses=ses_a')
    const setActiveId = vi.fn()
    renderHook(() => useDeepLink(setActiveId))
    expect(setActiveId).toHaveBeenCalledWith('ses_a')
    expect(getSnapshot().overlays.previewPath).toBe(null)
    expect(window.location.search).toBe('')
  })
})
