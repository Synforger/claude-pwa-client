import { describe, it, expect } from 'vitest'
import {
  MAX_PIXEL_SCALE,
  DOUBLE_TAP_ZOOM,
  ZOOM_ANIMATION_MS,
  ZOOM_EASING,
  PAN_END_FRICTION,
  LOWER_ZOOM_FRICTION,
  UPPER_ZOOM_FRICTION,
  DECELERATION_RATE,
  SPRING_FREQUENCY,
  VELOCITY_SAMPLE_MS,
  FIT_VIEW,
  fitScale,
  maxZoom,
  clampZoom,
  isFit,
  shownSize,
  panRange,
  clampView,
  resistZoom,
  resistPan,
  panBy,
  zoomAt,
  toggleZoomAt,
  span,
  dragTo,
  gestureTouches,
  wheelZoomFactor,
  wheelPanDelta,
  startVelocity,
  trackVelocity,
  releaseVelocity,
  cubicBezier,
  glideDistance,
  springOffset,
  springDuration,
  INITIAL_ZOOM_STATE,
  reduceZoom,
  viewAt,
  motionDone,
  restView,
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
  it('shows one image pixel per screen point at 1 / fitScale', () => {
    expect(shownSize(1 / fitScale(WIDE), WIDE).width).toBe(1600)
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

describe('toggleZoomAt (= ダブルタップ / ダブルクリックの行き先)', () => {
  it('goes one step in from the fit, around the point', () => {
    const point = { x: 100, y: 50 }
    const next = toggleZoomAt(FIT_VIEW, WIDE, point)
    expect(next.zoom).toBe(DOUBLE_TAP_ZOOM)
    expect(under(next, WIDE, point).fx).toBeCloseTo(0.25, 10)
    expect(under(next, WIDE, point).fy).toBeCloseTo(0.2, 10)
  })

  it('takes the same step whatever the pixel count of the image', () => {
    // 同じ形で画素数だけ違う 2 枚: 合わせの大きさが同じなら、 ダブルタップの後の大きさも同じ
    const big = { naturalWidth: 4000, naturalHeight: 2500, frameWidth: 400, frameHeight: 300 }
    const a = toggleZoomAt(FIT_VIEW, WIDE, { x: 100, y: 50 })
    const b = toggleZoomAt(FIT_VIEW, big, { x: 100, y: 50 })
    expect(shownSize(a.zoom, WIDE).width).toBeCloseTo(shownSize(b.zoom, big).width, 6)
    expect(shownSize(a.zoom, WIDE).height).toBeCloseTo(shownSize(b.zoom, big).height, 6)
    expect(a.x).toBeCloseTo(b.x, 6)
    expect(a.y).toBeCloseTo(b.y, 6)
  })

  it('goes back to the fit from any other zoom', () => {
    expect(toggleZoomAt({ zoom: DOUBLE_TAP_ZOOM, x: -300, y: -200 }, WIDE, { x: 5, y: 5 })).toEqual({ zoom: 1, x: 0, y: 0 })
    expect(toggleZoomAt({ zoom: 1.01, x: 0, y: 0 }, WIDE, { x: 5, y: 5 })).toEqual({ zoom: 1, x: 0, y: 0 })
    expect(toggleZoomAt({ zoom: maxZoom(WIDE), x: 0, y: 0 }, WIDE, { x: 5, y: 5 })).toEqual({ zoom: 1, x: 0, y: 0 })
  })

  it('steps in on a small image too', () => {
    const next = toggleZoomAt(FIT_VIEW, SMALL, { x: 200, y: 1 })
    expect(next.zoom).toBe(DOUBLE_TAP_ZOOM)
    expect(toggleZoomAt(next, SMALL, { x: 200, y: 1 }).zoom).toBe(1)
  })

  it('returns a scrolled tall image to the top when going back to the fit', () => {
    expect(toggleZoomAt({ zoom: 3, x: 0, y: -900 }, TALL, { x: 200, y: 100 })).toEqual({ zoom: 1, x: 100, y: 0 })
  })

  it('reads a zoom a rounding error away from 1 as the fit', () => {
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

describe('resistance (= 指が範囲を越えている間)', () => {
  it('shows only part of a zoom past either limit', () => {
    const max = maxZoom(WIDE)
    expect(resistZoom(2, WIDE)).toBe(2)
    expect(resistZoom(0.5, WIDE)).toBeCloseTo(1 - 0.5 * LOWER_ZOOM_FRICTION, 10)
    expect(resistZoom(max + 10, WIDE)).toBeCloseTo(max + 10 * UPPER_ZOOM_FRICTION, 10)
  })

  it('shows only part of a position past either edge', () => {
    expect(resistPan(-50, [-100, 0])).toBe(-50)
    expect(resistPan(40, [-100, 0])).toBeCloseTo(40 * PAN_END_FRICTION, 10)
    expect(resistPan(-140, [-100, 0])).toBeCloseTo(-100 - 40 * PAN_END_FRICTION, 10)
  })

  it('gives the range the image may sit in at a zoom', () => {
    expect(panRange(4, WIDE)).toEqual({ x: [-1200, 0], y: [-700, 0] })
    expect(panRange(1, WIDE)).toEqual({ x: [0, 0], y: [0, 0] })
    expect(panRange(1, TALL)).toEqual({ x: [100, 100], y: [-1700, 0] })
  })

  it('lets a finger pull the image past the edge, heavily', () => {
    const start = { zoom: 4, x: -10, y: -10 }
    const pulled = dragTo(start, WIDE, [{ x: 100, y: 100 }], [{ x: 210, y: 100 }], { soft: true })
    // 端を 100 越えて引いた → 見た目は 100 × 抵抗 だけ越える
    expect(pulled.x).toBeCloseTo(100 * PAN_END_FRICTION, 10)
    expect(pulled.y).toBe(-10)
  })

  it('lets two fingers pinch below the fit, heavily, and keeps a mouse at the limit', () => {
    const mid = { x: 200, y: 120 }
    const pair = (d) => [{ x: mid.x - d / 2, y: mid.y }, { x: mid.x + d / 2, y: mid.y }]
    const soft = dragTo(FIT_VIEW, WIDE, pair(200), pair(100), { soft: true })
    expect(soft.zoom).toBeCloseTo(1 - 0.5 * LOWER_ZOOM_FRICTION, 10)
    expect(dragTo(FIT_VIEW, WIDE, pair(200), pair(100)).zoom).toBe(1)
  })

  it('still depends only on where the fingers are now', () => {
    const start = { zoom: 4, x: -10, y: -10 }
    const from = [{ x: 100, y: 100 }]
    dragTo(start, WIDE, from, [{ x: 900, y: 900 }], { soft: true })
    expect(dragTo(start, WIDE, from, [{ x: 100, y: 100 }], { soft: true })).toEqual(start)
  })
})

describe('finger speed', () => {
  it('measures over at least the sampling interval', () => {
    let tracker = startVelocity({ x: 0, y: 0 }, 1000)
    tracker = trackVelocity(tracker, { x: 10, y: 0 }, 1000 + VELOCITY_SAMPLE_MS - 1)
    expect(tracker.vx).toBe(0) // まだ測らない
    tracker = trackVelocity(tracker, { x: 100, y: -50 }, 1000 + VELOCITY_SAMPLE_MS)
    expect(tracker.vx).toBeCloseTo(100 / VELOCITY_SAMPLE_MS, 10)
    expect(tracker.vy).toBeCloseTo(-50 / VELOCITY_SAMPLE_MS, 10)
  })

  it('gives the speed of the last stretch on release', () => {
    const tracker = trackVelocity(startVelocity({ x: 0, y: 0 }, 0), { x: 100, y: 0 }, 50)
    expect(releaseVelocity(tracker, { x: 130, y: 0 }, 60)).toEqual({ x: 3, y: 0 })
  })

  it('is zero when the finger rests before lifting, wherever the last mark was', () => {
    // 速く動かして (= 印は途中に残る)、 止めて、 離す
    let tracker = trackVelocity(startVelocity({ x: 0, y: 0 }, 0), { x: 100, y: 0 }, 50)
    tracker = trackVelocity(tracker, { x: 140, y: 0 }, 70) // 印はまだ 100 の所
    expect(tracker.x).toBe(100)
    expect(releaseVelocity(tracker, { x: 140, y: 0 }, 70 + VELOCITY_SAMPLE_MS)).toEqual({ x: 0, y: 0 })
    // 止めずに離せば、 最後の区間の速さ
    expect(releaseVelocity(tracker, { x: 140, y: 0 }, 80).x).toBeCloseTo(40 / 30, 10)
  })
})

describe('motion maths', () => {
  it('eases like the CSS curve: starts and ends exactly, slow in, fast through the middle', () => {
    expect(cubicBezier(ZOOM_EASING, 0)).toBe(0)
    expect(cubicBezier(ZOOM_EASING, 1)).toBe(1)
    const quarter = cubicBezier(ZOOM_EASING, 0.25)
    const half = cubicBezier(ZOOM_EASING, 0.5)
    expect(quarter).toBeGreaterThan(0)
    expect(half).toBeGreaterThan(quarter)
    expect(half).toBeGreaterThan(0.5) // この曲線は後半でゆっくり止まる
    expect(cubicBezier([0, 0, 1, 1], 0.3)).toBeCloseTo(0.3, 6) // 直線
  })

  it('glides a distance proportional to the release speed', () => {
    expect(glideDistance(1)).toBeCloseTo(DECELERATION_RATE / (1 - DECELERATION_RATE), 10)
    expect(glideDistance(-2)).toBeCloseTo(-2 * glideDistance(1), 10)
    expect(glideDistance(0)).toBe(0)
  })

  it('brings a spring from its start to rest without passing the end when critically damped', () => {
    expect(springOffset(100, 0, 1, SPRING_FREQUENCY, 0)).toBe(100)
    let last = 100
    for (let ms = 16; ms <= 1500; ms += 16) {
      const now = springOffset(100, 0, 1, SPRING_FREQUENCY, ms)
      expect(now).toBeGreaterThanOrEqual(0)
      expect(now).toBeLessThanOrEqual(last)
      last = now
    }
    expect(last).toBeLessThan(0.5)
  })

  it('passes the end and comes back when under-damped', () => {
    const samples = []
    for (let ms = 0; ms <= 1500; ms += 8) samples.push(springOffset(100, 0, 0.82, SPRING_FREQUENCY, ms))
    expect(Math.min(...samples)).toBeLessThan(0) // 行き過ぎる
    expect(Math.abs(samples[samples.length - 1])).toBeLessThan(0.5) // 戻って止まる
  })

  it('starts a spring at the speed it was released with', () => {
    // 始まりの傾き = 離した時の速さ (px / ms)
    const dt = 0.01
    const slope = (springOffset(0, 2, 1, SPRING_FREQUENCY, dt) - springOffset(0, 2, 1, SPRING_FREQUENCY, 0)) / dt
    expect(slope).toBeCloseTo(2, 2)
  })

  it('knows when a spring has come to rest', () => {
    const ms = springDuration(100, 0, 0.82, SPRING_FREQUENCY)
    expect(ms).toBeGreaterThan(100)
    for (let t = ms; t < ms + 500; t += 10) expect(Math.abs(springOffset(100, 0, 0.82, SPRING_FREQUENCY, t))).toBeLessThan(0.5)
  })
})

describe('reduceZoom (= 入力ごとの移り方)', () => {
  const geom = WIDE
  const one = (x, y) => [{ x, y }]
  const two = (mid, distance) => [{ x: mid.x - distance / 2, y: mid.y }, { x: mid.x + distance / 2, y: mid.y }]
  // 動きを最後まで進める
  const settle = (state, now = 1e6) => reduceZoom(state, { type: 'settle', geom, now })

  it('starts fitted, holding nothing, not moving', () => {
    expect(INITIAL_ZOOM_STATE).toEqual({ view: FIT_VIEW, grab: null, motion: null })
  })

  it('does not move until something is grabbed', () => {
    expect(reduceZoom(INITIAL_ZOOM_STATE, { type: 'move', geom, touches: one(50, 50) })).toBe(INITIAL_ZOOM_STATE)
  })

  it('pinches out with two fingers, then moves with the one that stays down', () => {
    const mid = { x: 100, y: 60 }
    let state = INITIAL_ZOOM_STATE
    state = reduceZoom(state, { type: 'grab', geom, soft: true, touches: one(70, 60) })
    state = reduceZoom(state, { type: 'grab', geom, soft: true, touches: two(mid, 60) })
    state = reduceZoom(state, { type: 'move', geom, touches: two(mid, 120) })
    state = reduceZoom(state, { type: 'move', geom, touches: two(mid, 180) })
    expect(state.view.zoom).toBeCloseTo(3, 10)
    expect(under(state.view, geom, mid).fx).toBeCloseTo(0.25, 10)

    // 1 本を離す: 残った指の今の位置が新しい基準になり、 画像は跳ばない
    const zoomed = state.view
    state = reduceZoom(state, { type: 'grab', geom, soft: true, touches: one(190, 60) })
    expect(state.view).toEqual(zoomed)
    state = reduceZoom(state, { type: 'move', geom, touches: one(160, 40) })
    expect(state.view).toEqual({ zoom: zoomed.zoom, x: zoomed.x - 30, y: zoomed.y - 20 })

    // 止めてから離す: 動かず、 その場に残る
    const moved = state.view
    state = reduceZoom(state, { type: 'release', geom, now: 0, velocity: { x: 0, y: 0 } })
    expect(state).toEqual({ view: moved, grab: null, motion: null })
  })

  it('ignores a move that does not match the grabbed fingers', () => {
    const state = reduceZoom(INITIAL_ZOOM_STATE, { type: 'grab', geom, soft: true, touches: one(70, 60) })
    expect(reduceZoom(state, { type: 'move', geom, touches: two({ x: 100, y: 60 }, 90) })).toBe(state)
  })

  it('glides on after a flick and comes to rest inside the range', () => {
    let state = { view: { zoom: 4, x: -600, y: -300 }, grab: null, motion: null }
    state = reduceZoom(state, { type: 'grab', geom, soft: true, now: 0, touches: one(200, 150) })
    state = reduceZoom(state, { type: 'move', geom, now: 16, touches: one(190, 150) })
    state = reduceZoom(state, { type: 'release', geom, now: 20, velocity: { x: -0.5, y: 0 } })
    expect(state.motion.kind).toBe('glide')
    const atRelease = viewAt(state, geom, 20)
    expect(atRelease.x).toBeCloseTo(-610, 6)
    const soon = viewAt(state, geom, 120)
    const later = viewAt(state, geom, 400)
    expect(soon.x).toBeLessThan(atRelease.x) // 離した後も同じ向きへ動き続ける
    expect(later.x).toBeLessThan(soon.x)
    expect(atRelease.x - soon.x).toBeGreaterThan(soon.x - viewAt(state, geom, 220).x) // 減速している
    const rest = restView(state, geom)
    expect(rest.x).toBeCloseTo(-610 + glideDistance(-0.5), 6)
    expect(motionDone(state, 20 + 5000)).toBe(true)
    expect(settle(state).view).toEqual(rest)
    expect(settle(state).motion).toBeNull()
  })

  it('runs past the edge on a hard flick, then comes back to the edge', () => {
    let state = { view: { zoom: 4, x: -50, y: -300 }, grab: null, motion: null }
    state = reduceZoom(state, { type: 'grab', geom, soft: true, now: 0, touches: one(200, 150) })
    state = reduceZoom(state, { type: 'release', geom, now: 0, velocity: { x: 3, y: 0 } })
    const xs = []
    for (let ms = 0; ms <= 1500; ms += 8) xs.push(viewAt(state, geom, ms).x)
    expect(Math.max(...xs)).toBeGreaterThan(1) // 端 (= 0) を越える
    expect(restView(state, geom).x).toBe(0) // 落ち着く先は端
    expect(xs[xs.length - 1]).toBeCloseTo(0, 0)
  })

  it('springs back when released past the edge without speed', () => {
    let state = { view: { zoom: 4, x: -10, y: -10 }, grab: null, motion: null }
    state = reduceZoom(state, { type: 'grab', geom, soft: true, now: 0, touches: one(100, 100) })
    state = reduceZoom(state, { type: 'move', geom, now: 10, touches: one(310, 100) })
    expect(state.view.x).toBeGreaterThan(0) // 端を越えて引いている
    state = reduceZoom(state, { type: 'release', geom, now: 900, velocity: { x: 0, y: 0 } })
    expect(viewAt(state, geom, 900).x).toBeGreaterThan(0)
    expect(viewAt(state, geom, 960).x).toBeLessThan(viewAt(state, geom, 900).x) // 途中
    expect(settle(state).view.x).toBe(0) // 終わり
    // 端へ戻る時は、 端を少しだけ通り過ぎてから落ち着く (= 範囲の外からの戻りは、 行き過ぎるばね)
    const xs = []
    for (let ms = 900; ms <= 2400; ms += 8) xs.push(viewAt(state, geom, ms).x)
    expect(Math.min(...xs)).toBeLessThan(-0.5)
    expect(Math.min(...xs)).toBeGreaterThan(-20)
  })

  it('settles without passing its end when the glide stays inside the range', () => {
    let state = { view: { zoom: 4, x: -600, y: -300 }, grab: null, motion: null }
    state = reduceZoom(state, { type: 'grab', geom, soft: true, now: 0, touches: one(200, 150) })
    state = reduceZoom(state, { type: 'release', geom, now: 0, velocity: { x: -0.5, y: 0 } })
    const end = restView(state, geom).x
    for (let ms = 0; ms <= 3000; ms += 8) expect(viewAt(state, geom, ms).x).toBeGreaterThanOrEqual(end - 1e-6)
  })

  it('returns to the fit when a pinch is released below it', () => {
    const mid = { x: 200, y: 120 }
    let state = reduceZoom(INITIAL_ZOOM_STATE, { type: 'grab', geom, soft: true, now: 0, touches: two(mid, 200) })
    state = reduceZoom(state, { type: 'move', geom, now: 10, touches: two(mid, 100) })
    expect(state.view.zoom).toBeLessThan(1)
    state = reduceZoom(state, { type: 'release', geom, now: 20 })
    expect(state.motion.kind).toBe('correct')
    const mid1 = viewAt(state, geom, 40)
    expect(mid1.zoom).toBeGreaterThan(state.view.zoom)
    expect(mid1.zoom).toBeLessThan(1)
    expect(settle(state).view).toEqual({ zoom: 1, x: 0, y: 0 })
  })

  it('returns to the limit when a pinch is released above it, keeping the place between the fingers', () => {
    const mid = { x: 100, y: 60 }
    const max = maxZoom(geom)
    let state = { view: clampView({ zoom: max, x: -3000, y: -2000 }, geom), grab: null, motion: null }
    const before = under(state.view, geom, mid)
    state = reduceZoom(state, { type: 'grab', geom, soft: true, now: 0, touches: two(mid, 100) })
    state = reduceZoom(state, { type: 'move', geom, now: 10, touches: two(mid, 300) })
    expect(state.view.zoom).toBeGreaterThan(max)
    state = reduceZoom(state, { type: 'release', geom, now: 20 })
    const rest = settle(state).view
    expect(rest.zoom).toBe(max)
    expect(under(rest, geom, mid).fx).toBeCloseTo(before.fx, 6)
  })

  it('does not glide after a pinch ends', () => {
    const mid = { x: 100, y: 60 }
    let state = reduceZoom(INITIAL_ZOOM_STATE, { type: 'grab', geom, soft: true, now: 0, touches: two(mid, 60) })
    state = reduceZoom(state, { type: 'move', geom, now: 10, touches: two(mid, 180) })
    state = reduceZoom(state, { type: 'release', geom, now: 20, velocity: { x: 5, y: 5 } })
    expect(state.motion).toBeNull()
  })

  it('lets go of an over-pinched image when one of the two fingers lifts', () => {
    const mid = { x: 200, y: 120 }
    let state = reduceZoom(INITIAL_ZOOM_STATE, { type: 'grab', geom, soft: true, now: 0, touches: two(mid, 200) })
    state = reduceZoom(state, { type: 'move', geom, now: 10, touches: two(mid, 100) })
    state = reduceZoom(state, { type: 'grab', geom, soft: true, now: 20, touches: one(150, 120) })
    expect(state.grab).toBeNull()
    expect(state.motion.kind).toBe('correct')
    // 残った指が動いても、 離れても、 戻りは続く
    const moving = reduceZoom(state, { type: 'move', geom, now: 30, touches: one(10, 10) })
    expect(moving).toBe(state)
    expect(reduceZoom(state, { type: 'release', geom, now: 40 })).toBe(state)
  })

  it('keeps a mouse drag inside the range and does not glide', () => {
    let state = { view: { zoom: 4, x: -10, y: -10 }, grab: null, motion: null }
    state = reduceZoom(state, { type: 'grab', geom, soft: false, now: 0, touches: one(100, 100) })
    state = reduceZoom(state, { type: 'move', geom, now: 10, touches: one(400, 400) })
    expect(state.view).toEqual({ zoom: 4, x: 0, y: 0 })
    state = reduceZoom(state, { type: 'release', geom, now: 20, velocity: { x: 9, y: 9 } })
    expect(state).toEqual({ view: { zoom: 4, x: 0, y: 0 }, grab: null, motion: null })
  })

  it('animates a double tap: start, middle and end', () => {
    const point = { x: 100, y: 50 }
    const state = reduceZoom(INITIAL_ZOOM_STATE, { type: 'toggle', geom, now: 1000, point, animate: true })
    expect(state.motion.kind).toBe('tween')
    expect(viewAt(state, geom, 1000)).toEqual({ zoom: 1, x: 0, y: 0 })
    const mid = viewAt(state, geom, 1000 + ZOOM_ANIMATION_MS / 2)
    expect(mid.zoom).toBeGreaterThan(1)
    expect(mid.zoom).toBeLessThan(DOUBLE_TAP_ZOOM)
    expect(motionDone(state, 1000 + ZOOM_ANIMATION_MS - 1)).toBe(false)
    expect(motionDone(state, 1000 + ZOOM_ANIMATION_MS)).toBe(true)
    const end = viewAt(state, geom, 1000 + ZOOM_ANIMATION_MS)
    expect(end.zoom).toBe(DOUBLE_TAP_ZOOM)
    expect(under(end, geom, point).fx).toBeCloseTo(0.25, 10)
    expect(settle(state).view).toEqual(end)
  })

  it('jumps without animating when asked to', () => {
    const state = reduceZoom(INITIAL_ZOOM_STATE, { type: 'toggle', geom, now: 0, point: { x: 100, y: 50 }, animate: false })
    expect(state.motion).toBeNull()
    expect(state.view.zoom).toBe(DOUBLE_TAP_ZOOM)
  })

  it('turns back from where it is when double-tapped again mid-way', () => {
    const point = { x: 100, y: 50 }
    let state = reduceZoom(INITIAL_ZOOM_STATE, { type: 'toggle', geom, now: 0, point, animate: true })
    const half = viewAt(state, geom, 150)
    state = reduceZoom(state, { type: 'toggle', geom, now: 150, point, animate: true })
    // 行き先は合わせ (= 拡大へ向かっていたので)、 始まりは今居る所 (= 跳ばない)
    expect(viewAt(state, geom, 150)).toEqual(half)
    expect(restView(state, geom)).toEqual({ zoom: 1, x: 0, y: 0 })
  })

  it('turns back toward the zoom when double-tapped again on the way out', () => {
    const point = { x: 100, y: 50 }
    let state = settle(reduceZoom(INITIAL_ZOOM_STATE, { type: 'toggle', geom, now: 0, point, animate: true }))
    expect(state.view.zoom).toBe(DOUBLE_TAP_ZOOM)
    state = reduceZoom(state, { type: 'toggle', geom, now: 1000, point, animate: true }) // 合わせへ戻り始める
    expect(restView(state, geom).zoom).toBe(1)
    const half = viewAt(state, geom, 1150)
    state = reduceZoom(state, { type: 'toggle', geom, now: 1150, point, animate: true }) // 途中でもう一度
    expect(viewAt(state, geom, 1150)).toEqual(half)
    expect(restView(state, geom).zoom).toBe(DOUBLE_TAP_ZOOM) // 行き先 (= 合わせ) から見て、 拡大へ引き返す
  })

  it('is caught where it is when a finger lands mid-motion', () => {
    let state = { view: { zoom: 4, x: -600, y: -300 }, grab: null, motion: null }
    state = reduceZoom(state, { type: 'grab', geom, soft: true, now: 0, touches: one(200, 150) })
    state = reduceZoom(state, { type: 'release', geom, now: 0, velocity: { x: -1, y: 0 } })
    const midway = viewAt(state, geom, 200)
    state = reduceZoom(state, { type: 'grab', geom, soft: true, now: 200, touches: one(50, 50) })
    expect(state.motion).toBeNull()
    expect(state.view).toEqual(midway) // 滑っていた所で止まる
    state = reduceZoom(state, { type: 'move', geom, now: 210, touches: one(60, 50) })
    expect(state.view.x).toBeCloseTo(midway.x + 10, 6) // そこから指に付いて動く
  })

  it('takes a wheel mid-motion from where the image is', () => {
    const point = { x: 100, y: 50 }
    let state = reduceZoom(INITIAL_ZOOM_STATE, { type: 'toggle', geom, now: 0, point, animate: true })
    const half = clampView(viewAt(state, geom, 150), geom)
    state = reduceZoom(state, { type: 'wheel-pan', geom, now: 150, dx: -5, dy: 0 })
    expect(state.motion).toBeNull()
    expect(state.view).toEqual(panBy(half, geom, -5, 0))
  })

  it('zooms with the wheel about the cursor and drops what was grabbed', () => {
    let state = reduceZoom(INITIAL_ZOOM_STATE, { type: 'grab', geom, soft: false, touches: one(70, 60) })
    const point = { x: 300, y: 100 }
    state = reduceZoom(state, { type: 'wheel-zoom', geom, point, factor: 2 })
    expect(state.view.zoom).toBe(2)
    expect(under(state.view, geom, point).fx).toBeCloseTo(0.75, 10)
    expect(state.grab).toBeNull()
    expect(reduceZoom(state, { type: 'move', geom, touches: one(90, 90) })).toBe(state)
  })

  it('scrolls with a plain wheel', () => {
    const state = reduceZoom(INITIAL_ZOOM_STATE, { type: 'wheel-pan', geom: TALL, dx: 0, dy: -250 })
    expect(state.view).toEqual({ zoom: 1, x: 100, y: -250 })
  })

  it('glides a fitted tall image after a flick, like a page', () => {
    let state = reduceZoom(INITIAL_ZOOM_STATE, { type: 'grab', geom: TALL, soft: true, now: 0, touches: one(200, 200) })
    state = reduceZoom(state, { type: 'move', geom: TALL, now: 16, touches: one(200, 150) })
    state = reduceZoom(state, { type: 'release', geom: TALL, now: 20, velocity: { x: 0, y: -1 } })
    expect(state.motion.kind).toBe('glide')
    expect(viewAt(state, TALL, 300).y).toBeLessThan(viewAt(state, TALL, 20).y)
    const rest = restView(state, TALL)
    expect(rest.x).toBe(100)
    expect(rest.y).toBeCloseTo(-50 + glideDistance(-1), 6)
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
    let state = reduceZoom(INITIAL_ZOOM_STATE, { type: 'grab', geom, soft: false, touches: gestureTouches(point, 1) })
    state = reduceZoom(state, { type: 'move', geom, touches: gestureTouches(point, 1.5) })
    state = reduceZoom(state, { type: 'move', geom, touches: gestureTouches(point, 3) })
    expect(state.view.zoom).toBeCloseTo(3, 10)
    expect(under(state.view, geom, point).fx).toBeCloseTo(0.25, 10)

    state = reduceZoom(state, { type: 'release', geom })
    expect(state.grab).toBeNull()
    expect(state.motion).toBeNull()
    expect(state.view.zoom).toBeCloseTo(3, 10)
  })

  it('starts the next gesture from where the last one ended', () => {
    const point = { x: 100, y: 60 }
    let state = reduceZoom(INITIAL_ZOOM_STATE, { type: 'grab', geom, soft: false, touches: gestureTouches(point, 1) })
    state = reduceZoom(state, { type: 'move', geom, touches: gestureTouches(point, 2) })
    state = reduceZoom(state, { type: 'release', geom })
    state = reduceZoom(state, { type: 'grab', geom, soft: false, touches: gestureTouches(point, 1) })
    state = reduceZoom(state, { type: 'move', geom, touches: gestureTouches(point, 2) })
    expect(state.view.zoom).toBeCloseTo(4, 10)
  })

  it('pinches back in no further than the fit (a trackpad stops at the limit)', () => {
    const point = { x: 100, y: 60 }
    let state = reduceZoom(INITIAL_ZOOM_STATE, { type: 'grab', geom, soft: false, touches: gestureTouches(point, 1) })
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
