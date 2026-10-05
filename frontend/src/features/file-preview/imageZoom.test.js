import { describe, it, expect } from 'vitest'
import {
  MAX_PIXEL_SCALE,
  FIT_VIEW,
  fitScale,
  actualSizeZoom,
  maxZoom,
  clampZoom,
  isFit,
  shownSize,
  clampView,
  panBy,
  zoomAt,
  toggleZoomAt,
  span,
  dragTo,
  INITIAL_ZOOM_STATE,
  reduceZoom,
  gestureTouches,
  wheelZoomFactor,
  wheelPanDelta,
} from './imageZoom.js'

// 枠 400 x 300 に対して: 幅が溢れる画像 / 縦に長い画像 / 枠より小さい画像
const WIDE = { naturalWidth: 1600, naturalHeight: 1000, frameWidth: 400, frameHeight: 300 }
const TALL = { naturalWidth: 200, naturalHeight: 2000, frameWidth: 400, frameHeight: 300 }
const SMALL = { naturalWidth: 2, naturalHeight: 2, frameWidth: 400, frameHeight: 300 }

// 枠の中の点 point の下に在る、 画像の中の場所 (= 画像の幅・高さに対する割合)
function under(view, geom, point) {
  const { width, height } = shownSize(view.zoom, geom)
  return { fx: (point.x - view.x) / width, fy: (point.y - view.y) / height }
}

describe('fit (= 合わせ)', () => {
  it('shrinks an image wider than the frame to the frame width', () => {
    expect(fitScale(WIDE)).toBe(0.25)
    expect(shownSize(1, WIDE)).toEqual({ width: 400, height: 250 })
  })

  it('keeps an image narrower than the frame at its own size', () => {
    expect(fitScale(TALL)).toBe(1)
    expect(fitScale(SMALL)).toBe(1)
    expect(shownSize(1, SMALL)).toEqual({ width: 2, height: 2 })
  })

  it('does not divide by a size that has not been measured yet', () => {
    expect(fitScale({ naturalWidth: 0, naturalHeight: 0, frameWidth: 400, frameHeight: 300 })).toBe(1)
    expect(fitScale({ naturalWidth: 100, naturalHeight: 100, frameWidth: 0, frameHeight: 0 })).toBe(1)
  })

  it('puts the fitted image at the top, centred across the frame', () => {
    expect(clampView(FIT_VIEW, WIDE)).toEqual({ zoom: 1, x: 0, y: 0 })
    expect(clampView(FIT_VIEW, TALL)).toEqual({ zoom: 1, x: 100, y: 0 })
    expect(clampView(FIT_VIEW, SMALL)).toEqual({ zoom: 1, x: 199, y: 0 })
  })

  it('stays fitted when the frame changes size', () => {
    const rotated = { ...WIDE, frameWidth: 800, frameHeight: 200 }
    expect(shownSize(clampView(FIT_VIEW, rotated).zoom, rotated).width).toBe(800)
  })
})

describe('zoom limits', () => {
  it('reaches actual size at 1 / fitScale', () => {
    expect(actualSizeZoom(WIDE)).toBe(4)
    expect(shownSize(actualSizeZoom(WIDE), WIDE).width).toBe(1600)
    expect(actualSizeZoom(SMALL)).toBe(1)
  })

  it('caps the zoom at MAX_PIXEL_SCALE screen points per image pixel', () => {
    expect(maxZoom(WIDE)).toBe(MAX_PIXEL_SCALE * 4)
    expect(shownSize(maxZoom(WIDE), WIDE).width).toBe(1600 * MAX_PIXEL_SCALE)
    expect(maxZoom(SMALL)).toBe(MAX_PIXEL_SCALE)
  })

  it('never goes below the fit, never above the cap', () => {
    expect(clampZoom(0.2, WIDE)).toBe(1)
    expect(clampZoom(1e9, WIDE)).toBe(maxZoom(WIDE))
    expect(clampZoom(NaN, WIDE)).toBe(1)
    expect(clampView({ zoom: 0.5, x: 0, y: 0 }, WIDE).zoom).toBe(1)
  })
})

describe('clampView (= 画像が枠の外へ出て行かない)', () => {
  it('keeps a larger image covering the frame on both axes', () => {
    // zoom 4 = 1600 x 1000 を 400 x 300 の枠で見る → x は [-1200, 0]、 y は [-700, 0]
    expect(clampView({ zoom: 4, x: 50, y: 50 }, WIDE)).toEqual({ zoom: 4, x: 0, y: 0 })
    expect(clampView({ zoom: 4, x: -5000, y: -5000 }, WIDE)).toEqual({ zoom: 4, x: -1200, y: -700 })
    expect(clampView({ zoom: 4, x: -300, y: -200 }, WIDE)).toEqual({ zoom: 4, x: -300, y: -200 })
  })

  it('centres an axis that is narrower than the frame and pins a shorter one to the top', () => {
    // zoom 1.2 = 480 x 300: 横は溢れる、 縦は枠ちょうど
    expect(clampView({ zoom: 1.2, x: -40, y: -99 }, WIDE)).toEqual({ zoom: 1.2, x: -40, y: 0 })
    // 小さい画像を 8 倍 = 16 x 16: どちらも枠より小さい
    expect(clampView({ zoom: 8, x: -3, y: 77 }, SMALL)).toEqual({ zoom: 8, x: 192, y: 0 })
  })

  it('lets a tall image be scrolled at fit, within its height', () => {
    expect(clampView({ zoom: 1, x: 0, y: -500 }, TALL)).toEqual({ zoom: 1, x: 100, y: -500 })
    expect(clampView({ zoom: 1, x: 0, y: -9999 }, TALL)).toEqual({ zoom: 1, x: 100, y: -1700 })
    expect(clampView({ zoom: 1, x: 0, y: 30 }, TALL)).toEqual({ zoom: 1, x: 100, y: 0 })
  })

  it('treats a position that is not a number as the origin', () => {
    expect(clampView({ zoom: 4, x: NaN, y: undefined }, WIDE)).toEqual({ zoom: 4, x: 0, y: 0 })
  })
})

describe('panBy', () => {
  it('moves by the given distance inside the range', () => {
    expect(panBy({ zoom: 4, x: -300, y: -200 }, WIDE, 30, -20)).toEqual({ zoom: 4, x: -270, y: -220 })
  })

  it('stops at the edge', () => {
    expect(panBy({ zoom: 4, x: -10, y: -10 }, WIDE, 500, 500)).toEqual({ zoom: 4, x: 0, y: 0 })
    expect(panBy({ zoom: 4, x: -1190, y: -690 }, WIDE, -500, -500)).toEqual({ zoom: 4, x: -1200, y: -700 })
  })

  it('does nothing to a fitted image that has no room to move', () => {
    expect(panBy(FIT_VIEW, WIDE, 80, 80)).toEqual({ zoom: 1, x: 0, y: 0 })
  })

  it('scrolls a fitted tall image', () => {
    expect(panBy(FIT_VIEW, TALL, 0, -250)).toEqual({ zoom: 1, x: 100, y: -250 })
  })
})

describe('zoomAt (= ある点を中心に倍率を変える)', () => {
  it('keeps the place under the point where it was', () => {
    const start = { zoom: 4, x: -300, y: -200 }
    const point = { x: 120, y: 90 }
    const next = zoomAt(start, WIDE, point, 6)
    expect(next.zoom).toBe(6)
    const before = under(start, WIDE, point)
    const after = under(next, WIDE, point)
    expect(after.fx).toBeCloseTo(before.fx, 10)
    expect(after.fy).toBeCloseTo(before.fy, 10)
  })

  it('keeps the point across the frame when zooming in from fit', () => {
    const point = { x: 300, y: 100 }
    const next = zoomAt(FIT_VIEW, WIDE, point, 4)
    expect(under(next, WIDE, point).fx).toBeCloseTo(under(clampView(FIT_VIEW, WIDE), WIDE, point).fx, 10)
    expect(next).toEqual({ zoom: 4, x: -900, y: -300 })
  })

  it('gives way to the edge when the point would pull the image off the frame', () => {
    // 右下いっぱいまで寄せた所から、 左上の点を中心に縮める → 範囲の端に収まる
    const next = zoomAt({ zoom: 4, x: -1200, y: -700 }, WIDE, { x: 0, y: 0 }, 2)
    expect(next).toEqual({ zoom: 2, x: -400, y: -200 })
  })

  it('clamps the requested zoom', () => {
    expect(zoomAt(FIT_VIEW, WIDE, { x: 10, y: 10 }, 0.1)).toEqual({ zoom: 1, x: 0, y: 0 })
    expect(zoomAt(FIT_VIEW, WIDE, { x: 0, y: 0 }, 1e9).zoom).toBe(maxZoom(WIDE))
  })
})

describe('toggleZoomAt (= ダブルタップ / ダブルクリック)', () => {
  it('goes from fit to actual size around the point', () => {
    const point = { x: 100, y: 50 }
    const next = toggleZoomAt(FIT_VIEW, WIDE, point)
    expect(next.zoom).toBe(4)
    expect(shownSize(next.zoom, WIDE).width).toBe(1600)
    expect(under(next, WIDE, point).fx).toBeCloseTo(0.25, 10)
    expect(under(next, WIDE, point).fy).toBeCloseTo(0.2, 10)
  })

  it('goes back to fit from anywhere else', () => {
    expect(toggleZoomAt({ zoom: 4, x: -300, y: -200 }, WIDE, { x: 5, y: 5 })).toEqual({ zoom: 1, x: 0, y: 0 })
    expect(toggleZoomAt({ zoom: 1.01, x: 0, y: 0 }, WIDE, { x: 5, y: 5 })).toEqual({ zoom: 1, x: 0, y: 0 })
  })

  it('goes to the cap when actual size is no larger than fit', () => {
    const next = toggleZoomAt(FIT_VIEW, SMALL, { x: 200, y: 1 })
    expect(next.zoom).toBe(MAX_PIXEL_SCALE)
    expect(toggleZoomAt(next, SMALL, { x: 200, y: 1 }).zoom).toBe(1)
  })

  it('returns a scrolled tall image to the top when going back to fit', () => {
    const scrolledAtFit = { zoom: 1, x: 100, y: -500 }
    // 合わせの時のダブルタップは拡大 (= 縦に長い画像は等倍 = 合わせなので上限へ)
    expect(toggleZoomAt(scrolledAtFit, TALL, { x: 200, y: 100 }).zoom).toBe(MAX_PIXEL_SCALE)
    expect(toggleZoomAt({ zoom: 3, x: 0, y: -900 }, TALL, { x: 200, y: 100 })).toEqual({ zoom: 1, x: 100, y: 0 })
  })

  it('reads a zoom a rounding error away from 1 as fit', () => {
    expect(isFit({ zoom: 1 + 1e-9 })).toBe(true)
    expect(isFit({ zoom: 1.001 })).toBe(false)
  })
})

describe('dragTo (= 指 / ドラッグ)', () => {
  // 中点 mid、 間隔 distance で横に並んだ 2 本の指
  const fingers = (mid, distance) => [
    { x: mid.x - distance / 2, y: mid.y },
    { x: mid.x + distance / 2, y: mid.y },
  ]

  it('measures the midpoint and the distance between two points', () => {
    expect(span({ x: 0, y: 0 }, { x: 6, y: 8 })).toEqual({ x: 3, y: 4, distance: 10 })
  })

  it('moves the image with one finger', () => {
    const start = { zoom: 4, x: -300, y: -200 }
    expect(dragTo(start, WIDE, [{ x: 100, y: 100 }], [{ x: 130, y: 80 }])).toEqual({ zoom: 4, x: -270, y: -220 })
  })

  it('stops at the edge, and comes back with the finger rather than ahead of it', () => {
    const start = { zoom: 4, x: -10, y: -10 }
    const from = [{ x: 100, y: 100 }]
    // 端を 490 px 越えて引いても端で止まる
    expect(dragTo(start, WIDE, from, [{ x: 600, y: 600 }])).toEqual({ zoom: 4, x: 0, y: 0 })
    // 指が触れ始めた所へ戻れば、 画像も触れ始めた所へ戻る (= 越えた分を先に戻り切ってから動く)
    expect(dragTo(start, WIDE, from, [{ x: 100, y: 100 }])).toEqual(start)
  })

  it('zooms about the midpoint by the ratio of the finger spans', () => {
    const start = { zoom: 2, x: -100, y: -50 }
    const mid = { x: 200, y: 120 }
    const next = dragTo(start, WIDE, fingers(mid, 100), fingers(mid, 150))
    expect(next.zoom).toBeCloseTo(3, 10)
    expect(under(next, WIDE, mid).fx).toBeCloseTo(under(start, WIDE, mid).fx, 10)
    expect(under(next, WIDE, mid).fy).toBeCloseTo(under(start, WIDE, mid).fy, 10)
  })

  it('keeps the place between the fingers there when zooming in from fit', () => {
    const mid = { x: 100, y: 60 }
    const next = dragTo(FIT_VIEW, WIDE, fingers(mid, 60), fingers(mid, 180))
    expect(next.zoom).toBeCloseTo(3, 10)
    expect(under(next, WIDE, mid).fx).toBeCloseTo(0.25, 10)
  })

  it('carries the image along when the midpoint moves', () => {
    const start = { zoom: 4, x: -300, y: -200 }
    const next = dragTo(start, WIDE, fingers({ x: 200, y: 120 }, 100), fingers({ x: 230, y: 100 }, 100))
    expect(next).toEqual({ zoom: 4, x: -270, y: -220 })
  })

  it('depends only on where the fingers are now, not on how they got there', () => {
    const start = { zoom: 2, x: -100, y: -50 }
    const from = fingers({ x: 200, y: 120 }, 100)
    const to = fingers({ x: 180, y: 140 }, 260)
    const direct = dragTo(start, WIDE, from, to)
    // 途中で大きく縮めて端に当ててから同じ位置へ来ても、 結果は同じ
    dragTo(start, WIDE, from, fingers({ x: 900, y: 900 }, 5))
    expect(dragTo(start, WIDE, from, to)).toEqual(direct)
  })

  it('does not shrink below fit', () => {
    const mid = { x: 200, y: 120 }
    expect(dragTo(FIT_VIEW, WIDE, fingers(mid, 200), fingers(mid, 20))).toEqual({ zoom: 1, x: 0, y: 0 })
  })

  it('keeps the zoom when the fingers start on the same point', () => {
    const start = { zoom: 2, x: -100, y: -50 }
    const same = [{ x: 1, y: 1 }, { x: 1, y: 1 }]
    expect(dragTo(start, WIDE, same, fingers({ x: 1, y: 1 }, 50))).toEqual(start)
  })

  it('ignores a move whose finger count differs from the grab', () => {
    const start = { zoom: 2, x: -100, y: -50 }
    expect(dragTo(start, WIDE, [{ x: 0, y: 0 }], fingers({ x: 9, y: 9 }, 50))).toEqual(start)
    expect(dragTo(start, WIDE, [], [])).toEqual(start)
  })
})

describe('reduceZoom (= 入力ごとの移り方)', () => {
  const geom = WIDE
  const one = (x, y) => [{ x, y }]
  const two = (mid, distance) => [{ x: mid.x - distance / 2, y: mid.y }, { x: mid.x + distance / 2, y: mid.y }]

  it('starts fitted, holding nothing', () => {
    expect(INITIAL_ZOOM_STATE).toEqual({ view: FIT_VIEW, grab: null })
  })

  it('does not move until something is grabbed', () => {
    expect(reduceZoom(INITIAL_ZOOM_STATE, { type: 'move', geom, touches: one(50, 50) })).toBe(INITIAL_ZOOM_STATE)
  })

  it('pinches out with two fingers, then moves with the one that stays down', () => {
    const mid = { x: 100, y: 60 }
    let state = INITIAL_ZOOM_STATE
    state = reduceZoom(state, { type: 'grab', geom, touches: one(70, 60) })
    state = reduceZoom(state, { type: 'grab', geom, touches: two(mid, 60) })
    state = reduceZoom(state, { type: 'move', geom, touches: two(mid, 120) })
    state = reduceZoom(state, { type: 'move', geom, touches: two(mid, 180) })
    expect(state.view.zoom).toBeCloseTo(3, 10)
    expect(under(state.view, geom, mid).fx).toBeCloseTo(0.25, 10)

    // 1 本を離す: 残った指の今の位置が新しい基準になり、 画像は跳ばない
    const zoomed = state.view
    state = reduceZoom(state, { type: 'grab', geom, touches: one(190, 60) })
    expect(state.view).toEqual(zoomed)
    state = reduceZoom(state, { type: 'move', geom, touches: one(160, 40) })
    expect(state.view).toEqual({ zoom: zoomed.zoom, x: zoomed.x - 30, y: zoomed.y - 20 })

    // 全部離す: 基準は消え、 view は残る
    const moved = state.view
    state = reduceZoom(state, { type: 'grab', geom, touches: [] })
    expect(state).toEqual({ view: moved, grab: null })
  })

  it('ignores a move that does not match the grabbed fingers', () => {
    let state = reduceZoom(INITIAL_ZOOM_STATE, { type: 'grab', geom, touches: one(70, 60) })
    expect(reduceZoom(state, { type: 'move', geom, touches: two({ x: 100, y: 60 }, 90) })).toBe(state)
  })

  it('zooms with the wheel about the cursor and drops what was grabbed', () => {
    let state = reduceZoom(INITIAL_ZOOM_STATE, { type: 'grab', geom, touches: one(70, 60) })
    const point = { x: 300, y: 100 }
    state = reduceZoom(state, { type: 'wheel-zoom', geom, point, factor: 2 })
    expect(state.view.zoom).toBe(2)
    expect(under(state.view, geom, point).fx).toBeCloseTo(0.75, 10)
    expect(state.grab).toBeNull()
    // 掴んだ基準は消えているので、 続く指の動きで wheel の拡大が巻き戻らない
    expect(reduceZoom(state, { type: 'move', geom, touches: one(90, 90) })).toBe(state)
  })

  it('scrolls with a plain wheel', () => {
    const state = reduceZoom(INITIAL_ZOOM_STATE, { type: 'wheel-pan', geom: TALL, dx: 0, dy: -250 })
    expect(state.view).toEqual({ zoom: 1, x: 100, y: -250 })
  })

  it('toggles between fit and actual size', () => {
    let state = reduceZoom(INITIAL_ZOOM_STATE, { type: 'toggle', geom, point: { x: 100, y: 50 } })
    expect(state.view.zoom).toBe(4)
    state = reduceZoom(state, { type: 'toggle', geom, point: { x: 100, y: 50 } })
    expect(state.view).toEqual({ zoom: 1, x: 0, y: 0 })
  })

  it('leaves the state alone for an action it does not know', () => {
    expect(reduceZoom(INITIAL_ZOOM_STATE, { type: 'nope', geom })).toBe(INITIAL_ZOOM_STATE)
  })
})

describe('gestureTouches (= Safari の trackpad のピンチ)', () => {
  const geom = WIDE

  it('turns a centre and a scale into two points that far apart around the centre', () => {
    const touches = gestureTouches({ x: 120, y: 80 }, 3)
    expect(span(touches[0], touches[1])).toEqual({ x: 120, y: 80, distance: 3 })
  })

  it('zooms by the scale the gesture reports, about where the pointer is', () => {
    const point = { x: 100, y: 60 }
    let state = reduceZoom(INITIAL_ZOOM_STATE, { type: 'grab', geom, touches: gestureTouches(point, 1) })
    state = reduceZoom(state, { type: 'move', geom, touches: gestureTouches(point, 1.5) })
    state = reduceZoom(state, { type: 'move', geom, touches: gestureTouches(point, 3) })
    expect(state.view.zoom).toBeCloseTo(3, 10)
    expect(under(state.view, geom, point).fx).toBeCloseTo(0.25, 10)

    state = reduceZoom(state, { type: 'grab', geom, touches: [] })
    expect(state.grab).toBeNull()
    expect(state.view.zoom).toBeCloseTo(3, 10)
  })

  it('starts the next gesture from where the last one ended', () => {
    const point = { x: 100, y: 60 }
    let state = reduceZoom(INITIAL_ZOOM_STATE, { type: 'grab', geom, touches: gestureTouches(point, 1) })
    state = reduceZoom(state, { type: 'move', geom, touches: gestureTouches(point, 2) })
    state = reduceZoom(state, { type: 'grab', geom, touches: [] })
    state = reduceZoom(state, { type: 'grab', geom, touches: gestureTouches(point, 1) })
    state = reduceZoom(state, { type: 'move', geom, touches: gestureTouches(point, 2) })
    expect(state.view.zoom).toBeCloseTo(4, 10)
  })

  it('pinches back in no further than the fit', () => {
    const point = { x: 100, y: 60 }
    let state = reduceZoom(INITIAL_ZOOM_STATE, { type: 'grab', geom, touches: gestureTouches(point, 1) })
    state = reduceZoom(state, { type: 'move', geom, touches: gestureTouches(point, 0.2) })
    expect(state.view).toEqual({ zoom: 1, x: 0, y: 0 })
  })

  it('reads a scale that is not a positive number as no change', () => {
    expect(gestureTouches({ x: 5, y: 5 }, NaN)).toEqual(gestureTouches({ x: 5, y: 5 }, 1))
    expect(gestureTouches({ x: 5, y: 5 }, 0)).toEqual(gestureTouches({ x: 5, y: 5 }, 1))
  })
})

describe('wheel', () => {
  it('zooms in when the wheel turns up and out when it turns down', () => {
    expect(wheelZoomFactor({ deltaY: -100, deltaMode: 0, ctrlKey: false })).toBeGreaterThan(1)
    expect(wheelZoomFactor({ deltaY: 100, deltaMode: 0, ctrlKey: false })).toBeLessThan(1)
    expect(wheelZoomFactor({ deltaY: 0, deltaMode: 0, ctrlKey: true })).toBe(1)
  })

  it('is symmetric: the same distance back undoes the zoom', () => {
    const up = wheelZoomFactor({ deltaY: -37, deltaMode: 0, ctrlKey: true })
    const down = wheelZoomFactor({ deltaY: 37, deltaMode: 0, ctrlKey: true })
    expect(up * down).toBeCloseTo(1, 12)
  })

  it('answers a trackpad pinch (ctrl + small deltas) ten times as strongly', () => {
    const plain = Math.log2(wheelZoomFactor({ deltaY: -5, deltaMode: 0, ctrlKey: false }))
    const pinch = Math.log2(wheelZoomFactor({ deltaY: -5, deltaMode: 0, ctrlKey: true }))
    expect(pinch / plain).toBeCloseTo(10, 10)
  })

  it('turns a plain wheel into a distance in px, whatever unit it arrives in', () => {
    expect(wheelPanDelta({ deltaX: 3, deltaY: 40, deltaMode: 0 }, WIDE)).toEqual({ x: 3, y: 40 })
    expect(wheelPanDelta({ deltaX: 0, deltaY: 3, deltaMode: 1 }, WIDE)).toEqual({ x: 0, y: 48 })
    expect(wheelPanDelta({ deltaX: 0, deltaY: 1, deltaMode: 2 }, WIDE)).toEqual({ x: 0, y: 300 })
  })
})
