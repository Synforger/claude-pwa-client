// @vitest-environment jsdom
//
// 画像のプレビューの契約 test: 拡大した状態は、 別の画像へ切り替えると合わせへ戻る。
// jsdom は大きさを持たないので、 枠の大きさと画像の画素数はここで与える。
import { it, expect, afterEach, beforeAll } from 'vitest'
import { render, cleanup, fireEvent, act } from '@testing-library/react'
import FilePreviewModal from './FilePreviewModal.jsx'
import { setOverlay } from '../../state/ui.js'

const FRAME = { width: 200, height: 100 }

beforeAll(() => {
  Object.defineProperty(HTMLElement.prototype, 'clientWidth', { configurable: true, get() { return FRAME.width } })
  Object.defineProperty(HTMLElement.prototype, 'clientHeight', { configurable: true, get() { return FRAME.height } })
})

afterEach(() => {
  act(() => setOverlay('previewPath', null))
  cleanup()
})

// 読み込みが済んだことにする (= 画素数を与えて load を起こす)
function load(img, width, height) {
  Object.defineProperty(img, 'naturalWidth', { configurable: true, value: width })
  Object.defineProperty(img, 'naturalHeight', { configurable: true, value: height })
  fireEvent.load(img)
}

it('opens an image fitted to the frame width', () => {
  act(() => setOverlay('previewPath', '/home/me/a.png'))
  const { getByTestId } = render(<FilePreviewModal />)
  const img = getByTestId('file-preview-image')
  expect(img.style.visibility).toBe('hidden')
  load(img, 800, 400)
  expect(img.style.visibility).toBe('')
  expect(img.style.width).toBe('200px')
  expect(img.style.height).toBe('100px')
  expect(img.style.transform).toBe('translate(0px, 0px)')
})

it('goes back to the fit when the preview switches to another image', () => {
  act(() => setOverlay('previewPath', '/home/me/a.png'))
  const { getByTestId } = render(<FilePreviewModal />)
  load(getByTestId('file-preview-image'), 800, 400)

  // ダブルクリックで等倍へ
  fireEvent.doubleClick(getByTestId('file-preview-image-frame'), { clientX: 50, clientY: 20 })
  expect(getByTestId('file-preview-image').style.width).toBe('800px')

  // 開いたまま別の画像へ
  act(() => setOverlay('previewPath', '/home/me/b.png'))
  const next = getByTestId('file-preview-image')
  expect(next.getAttribute('src')).toContain('b.png')
  load(next, 800, 400)
  expect(next.style.width).toBe('200px')
  expect(next.style.transform).toBe('translate(0px, 0px)')
})

it('keeps the zoom while the same image stays open', () => {
  act(() => setOverlay('previewPath', '/home/me/a.png'))
  const { getByTestId, rerender } = render(<FilePreviewModal />)
  load(getByTestId('file-preview-image'), 800, 400)
  fireEvent.doubleClick(getByTestId('file-preview-image-frame'), { clientX: 50, clientY: 20 })
  rerender(<FilePreviewModal />)
  expect(getByTestId('file-preview-image').style.width).toBe('800px')
})
