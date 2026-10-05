// @vitest-environment jsdom
//
// 画像のプレビューの契約 test: 拡大した状態は、 別の画像へ切り替えると合わせへ戻る。
// jsdom は大きさを持たないので、 枠の大きさと画像の画素数はここで与える。
import { it, expect, afterEach, beforeAll, beforeEach, vi } from 'vitest'
import { render, cleanup, fireEvent, act } from '@testing-library/react'
import FilePreviewModal from './FilePreviewModal.jsx'
import { setOverlay } from '../../state/ui.js'

const FRAME = { width: 200, height: 100 }

beforeAll(() => {
  Object.defineProperty(HTMLElement.prototype, 'clientWidth', { configurable: true, get() { return FRAME.width } })
  Object.defineProperty(HTMLElement.prototype, 'clientHeight', { configurable: true, get() { return FRAME.height } })
})

// ダブルクリックの拡大は時間を掛けて動くので、 時計を手で進める
beforeEach(() => { vi.useFakeTimers({ toFake: ['requestAnimationFrame', 'cancelAnimationFrame', 'performance', 'setTimeout', 'clearTimeout'] }) })

afterEach(() => {
  act(() => setOverlay('previewPath', null))
  cleanup()
  vi.useRealTimers()
})

// 動きが終わるまで時計を進める
function finishMotion() {
  act(() => { vi.advanceTimersByTime(1000) })
}

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

  // ダブルクリックで一段拡大 (= 合わせの 3 倍)
  fireEvent.doubleClick(getByTestId('file-preview-image-frame'), { clientX: 50, clientY: 20 })
  finishMotion()
  expect(getByTestId('file-preview-image').style.width).toBe('600px')

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
  finishMotion()
  rerender(<FilePreviewModal />)
  expect(getByTestId('file-preview-image').style.width).toBe('600px')
})

// Safari が trackpad のピンチで出す出来事 (= jsdom には型が無いので、 同じ名前と値を持つ出来事を作る)
function gesture(target, type, scale, clientX, clientY) {
  const event = new Event(type, { bubbles: true, cancelable: true })
  Object.assign(event, { scale, clientX, clientY })
  act(() => { target.dispatchEvent(event) })
  return event
}

it('zooms with the gesture events Safari sends for a trackpad pinch', () => {
  act(() => setOverlay('previewPath', '/home/me/a.png'))
  const { getByTestId } = render(<FilePreviewModal />)
  const img = getByTestId('file-preview-image')
  const frame = getByTestId('file-preview-image-frame')
  load(img, 800, 400)

  // 枠の (50, 20) を中心に 2 倍 → 400 x 200、 左へ 50・上へ 20 ずれる (= その点の下の場所は動かない)
  const start = gesture(frame, 'gesturestart', 1, 50, 20)
  const change = gesture(frame, 'gesturechange', 2, 50, 20)
  gesture(frame, 'gestureend', 2, 50, 20)
  expect(img.style.width).toBe('400px')
  expect(img.style.transform).toBe('translate(-50px, -20px)')
  // ブラウザ自体の拡大は止める
  expect(start.defaultPrevented).toBe(true)
  expect(change.defaultPrevented).toBe(true)

  // 次のピンチは、 前のピンチが終わった所から続く
  gesture(frame, 'gesturestart', 1, 50, 20)
  gesture(frame, 'gesturechange', 0.5, 50, 20)
  gesture(frame, 'gestureend', 0.5, 50, 20)
  expect(img.style.width).toBe('200px')
})

it('leaves a pinch to the fingers while they are down (iOS sends both)', () => {
  act(() => setOverlay('previewPath', '/home/me/a.png'))
  const { getByTestId } = render(<FilePreviewModal />)
  const img = getByTestId('file-preview-image')
  const frame = getByTestId('file-preview-image-frame')
  load(img, 800, 400)

  fireEvent.pointerDown(frame, { pointerId: 1, pointerType: 'touch', clientX: 40, clientY: 20, button: 0 })
  gesture(frame, 'gesturestart', 1, 50, 20)
  gesture(frame, 'gesturechange', 2, 50, 20)
  expect(img.style.width).toBe('200px')
})

it('moves through the double-click zoom instead of jumping', () => {
  act(() => setOverlay('previewPath', '/home/me/a.png'))
  const { getByTestId } = render(<FilePreviewModal />)
  const img = getByTestId('file-preview-image')
  load(img, 800, 400)

  fireEvent.doubleClick(getByTestId('file-preview-image-frame'), { clientX: 50, clientY: 20 })
  expect(img.style.width).toBe('200px') // 始まりは合わせのまま
  act(() => { vi.advanceTimersByTime(160) })
  const midway = parseFloat(img.style.width)
  expect(midway).toBeGreaterThan(200) // 途中
  expect(midway).toBeLessThan(600)
  finishMotion()
  expect(img.style.width).toBe('600px') // 終わり

  // 拡大している時は、 どの倍率からでも合わせへ戻る
  fireEvent.doubleClick(getByTestId('file-preview-image-frame'), { clientX: 50, clientY: 20 })
  finishMotion()
  expect(img.style.width).toBe('200px')
  expect(img.style.transform).toBe('translate(0px, 0px)')
})

it('opens fitted again after being closed while zoomed and still moving', () => {
  act(() => setOverlay('previewPath', '/home/me/a.png'))
  const { getByTestId, queryByTestId } = render(<FilePreviewModal />)
  load(getByTestId('file-preview-image'), 800, 400)
  fireEvent.doubleClick(getByTestId('file-preview-image-frame'), { clientX: 50, clientY: 20 })
  act(() => { vi.advanceTimersByTime(100) }) // 動いている途中で閉じる
  act(() => setOverlay('previewPath', null))
  expect(queryByTestId('file-preview-image')).toBeNull()
  act(() => { vi.advanceTimersByTime(1000) }) // 残った動きが、 消えた部品を触らない

  act(() => setOverlay('previewPath', '/home/me/a.png'))
  const again = getByTestId('file-preview-image')
  load(again, 800, 400)
  expect(again.style.width).toBe('200px')
  expect(again.style.transform).toBe('translate(0px, 0px)')
})
