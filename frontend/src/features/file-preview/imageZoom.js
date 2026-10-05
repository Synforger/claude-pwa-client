// 画像プレビューの拡大と移動の計算 (= 画面から切り離した純関数。 DOM には触らない)。
//
// 座標は「枠」 (= 画像を見せる領域) の左上を原点にした px。
//   view = { zoom, x, y }
//     zoom : 「合わせ」 を 1 とした倍率 (= 合わせ = 枠の幅に収めた大きさ。 枠より小さい画像は等倍のまま)
//     x, y : 画像の左上の位置
//   geom = { naturalWidth, naturalHeight, frameWidth, frameHeight }
//
// 拡大の状態は 1 つ (= 下の state)。 画面に出す大きさと位置は、 毎回 viewAt(state, geom, now) で
// そこから導く (= 枠の大きさが変わっても、 合わせは zoom = 1 のまま合わせで居続ける)。
//
// 指の動きは、 触れ始めた時の view と指の位置 (= grab) を基準に、 今の指の位置から直に求める
// (= 途中の経路に依らない。 端で止まった分の誤差が積もらない)。 指を離した後の動き (= 惰性、
// 端からの戻り、 ダブルタップの拡大) も、 始まった時の値と経過時間から直に求める (= motion)。
//
// 手触りの値は自作せず、 PhotoSwipe v5 (= iOS の写真アプリの動きを手本にした画像ビューア) の
// 既定をそのまま使う。 どの値がどこから来たかは、 各定数の横に書く。

// ---- 上限 ----

// 拡大の上限 (= 画像の 1 画素を、 画面の何点ぶんまで大きくできるか)。
// 無いと、 指を広げ続けるだけで画像が際限なく大きくなり、 どこを見ているか分からなくなる。
export const MAX_PIXEL_SCALE = 8

// ---- 手触りの値 (= PhotoSwipe v5.4 の既定) ----

// ダブルタップ / ダブルクリックで合わせから進む倍率。
// PhotoSwipe の 2 段目の倍率 (= slide/zoom-level.js `this.fit * 3`)。 PhotoSwipe は等倍を
// 越えない所で頭打ちにするが、 ここでは画素数に依らず同じ倍率にする (= 写真ごとに手触りを変えない)。
export const DOUBLE_TAP_ZOOM = 3

// ダブルタップの拡大・戻りに掛ける時間と緩急。
// PhotoSwipe の `zoomAnimationDuration: 333` と `easing: 'cubic-bezier(.4,0,.22,1)'`。
export const ZOOM_ANIMATION_MS = 333
export const ZOOM_EASING = Object.freeze([0.4, 0, 0.22, 1])

// 指で端を越えて引いた時、 越えた分のうち画面に出す割合 (= 抵抗)。
// PhotoSwipe の `PAN_END_FRICTION = 0.35` (gestures/drag-handler.js)。
export const PAN_END_FRICTION = 0.35

// 指で範囲を越えて拡大・縮小した時、 越えた分のうち画面に出す割合。
// PhotoSwipe の `LOWER_ZOOM_FRICTION = 0.15` / `UPPER_ZOOM_FRICTION = 0.05` (gestures/zoom-handler.js)。
export const LOWER_ZOOM_FRICTION = 0.15
export const UPPER_ZOOM_FRICTION = 0.05

// 指を離した後の惰性: 1ms ごとに速さがこの割合になる (= 0.5% ずつ失う)。
// PhotoSwipe の `decelerationRate = 0.995` (gestures/drag-handler.js)。 滑る距離 = 速さ × r / (1 - r)。
export const DECELERATION_RATE = 0.995

// 惰性と端からの戻りに使うばね。
// PhotoSwipe の `DEFAULT_NATURAL_FREQUENCY = 12` (util/spring-easer.js) と、 行き先が範囲の中なら
// 減衰比 1 (= 行き過ぎない)、 範囲の外へ出る勢いなら 0.82 (= 少し行き過ぎて戻る) (drag-handler.js)。
export const SPRING_FREQUENCY = 12
export const SPRING_DAMPING_SETTLE = 1
export const SPRING_DAMPING_OVERSHOOT = 0.82

// 範囲を越えた拡大・縮小から戻す時のばね (= 行き過ぎない、 速い)。
// PhotoSwipe の `dampingRatio: 1, naturalFrequency: 40` (zoom-handler.js の correctZoomPan)。
export const CORRECTION_FREQUENCY = 40

// 指の速さを測る間隔。 PhotoSwipe の「50ms ごとに速さを更新」 (gestures/gestures.js)。
export const VELOCITY_SAMPLE_MS = 50

// ---- 入力の単位 ----

// ホイールの回転量 → 倍率。 d3-zoom の既定 (= wheelDelta) と同じ式と係数:
//   倍率 = 2 ^ (-deltaY × 単位ごとの係数 × (ctrlKey なら 10))
// ctrlKey の 10 倍は、 trackpad のピンチ (= ブラウザが ctrl 付きの小さな wheel として届ける) のため。
const WHEEL_ZOOM_PER_PIXEL = 0.002
const WHEEL_ZOOM_PER_LINE = 0.05
const WHEEL_ZOOM_PER_PAGE = 1
const WHEEL_ZOOM_PINCH_GAIN = 10

// 行単位で届く wheel (= deltaMode 1) を px に直す時の 1 行の高さ。
const WHEEL_LINE_PX = 16

// 「合わせ」 かどうかの判定に使う誤差 (= 浮動小数の掛け算で 1 から僅かにずれた値を合わせと読む)。
const ZOOM_EPSILON = 1e-6

// 動きが「止まった」 と見なす残り (= 画面の半点。 これより小さい動きは見えない)。
const REST_PX = 0.5

export const FIT_VIEW = Object.freeze({ zoom: 1, x: 0, y: 0 })

const clamp = (value, min, max) => Math.min(Math.max(value, min), max)
const lerp = (a, b, p) => a + (b - a) * p

// ---- 大きさと範囲 ----

// 合わせの時に、 画像の 1 画素が画面の何点になるか (= 幅に収める。 拡大はしない)。
export function fitScale(geom) {
  const { naturalWidth, frameWidth } = geom
  if (!(naturalWidth > 0) || !(frameWidth > 0)) return 1
  return Math.min(1, frameWidth / naturalWidth)
}

// zoom の上限 (= 合わせより小さくはしないので、 下限は常に 1)。
export function maxZoom(geom) {
  return Math.max(1, MAX_PIXEL_SCALE / fitScale(geom))
}

export function clampZoom(zoom, geom) {
  if (!Number.isFinite(zoom)) return 1
  return clamp(zoom, 1, maxZoom(geom))
}

export function isFit(view) {
  return view.zoom <= 1 + ZOOM_EPSILON
}

// その zoom で画面に出る画像の大きさ。
export function shownSize(zoom, geom) {
  const scale = fitScale(geom) * zoom
  return { width: geom.naturalWidth * scale, height: geom.naturalHeight * scale }
}

// その zoom で、 画像の左上が居てよい範囲 (= 画像が枠の外へ出て行かない)。
//   横: 枠より狭ければ中央の 1 点、 広ければ枠を覆う範囲
//   縦: 枠より低ければ上端の 1 点、 高ければ枠を覆う範囲 (= 合わせで縦に長い画像は、 この範囲を送って読む)
export function panRange(zoom, geom) {
  const { width, height } = shownSize(zoom, geom)
  const { frameWidth, frameHeight } = geom
  const center = (frameWidth - width) / 2
  return {
    x: width <= frameWidth ? [center, center] : [frameWidth - width, 0],
    y: height <= frameHeight ? [0, 0] : [frameHeight - height, 0],
  }
}

// 倍率を範囲に収め、 位置をその倍率の範囲に収める。
export function clampView(view, geom) {
  const zoom = clampZoom(view.zoom, geom)
  const range = panRange(zoom, geom)
  return {
    zoom,
    x: clamp(Number.isFinite(view.x) ? view.x : 0, range.x[0], range.x[1]),
    y: clamp(Number.isFinite(view.y) ? view.y : 0, range.y[0], range.y[1]),
  }
}

// ---- 抵抗 (= 指が範囲を越えている間だけ、 越えた分を割り引いて見せる) ----

// 範囲を越えた倍率を、 抵抗を掛けた見た目の倍率にする。
export function resistZoom(zoom, geom) {
  const max = maxZoom(geom)
  if (zoom < 1) return 1 - (1 - zoom) * LOWER_ZOOM_FRICTION
  if (zoom > max) return max + (zoom - max) * UPPER_ZOOM_FRICTION
  return zoom
}

// 範囲 [lo, hi] を越えた位置を、 抵抗を掛けた見た目の位置にする。
export function resistPan(value, [lo, hi]) {
  if (value < lo) return lo + (value - lo) * PAN_END_FRICTION
  if (value > hi) return hi + (value - hi) * PAN_END_FRICTION
  return value
}

// ---- 1 回で決まる動き ----

// 画像を (dx, dy) だけ動かす (= 範囲の中で)。
export function panBy(view, geom, dx, dy) {
  const base = clampView(view, geom)
  return clampView({ zoom: base.zoom, x: base.x + dx, y: base.y + dy }, geom)
}

// 枠の中の点 point を中心に、 倍率を nextZoom にする (= その点の下に在る画像の場所が動かない)。
export function zoomAt(view, geom, point, nextZoom) {
  const base = clampView(view, geom)
  const zoom = clampZoom(nextZoom, geom)
  const ratio = zoom / base.zoom
  return clampView({
    zoom,
    x: point.x - (point.x - base.x) * ratio,
    y: point.y - (point.y - base.y) * ratio,
  }, geom)
}

// ダブルタップ / ダブルクリックの行き先: 合わせの時は point を中心に一段拡大、 それ以外は合わせ。
export function toggleZoomAt(view, geom, point) {
  const base = clampView(view, geom)
  if (!isFit(base)) return clampView(FIT_VIEW, geom)
  return zoomAt(base, geom, point, DOUBLE_TAP_ZOOM)
}

// 2 点の中点と間隔
export function span(a, b) {
  return { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2, distance: Math.hypot(a.x - b.x, a.y - b.y) }
}

// 指 (= またはドラッグ中のマウス) が from の位置から to の位置へ動いた時の view。
// start は触れ始めた時の view、 from / to は同じ順に並んだ点の配列。
//   1 点: 動いた分だけ画像を動かす (= 指の下の場所が指に付いて来る)
//   2 点: 中点の下に在った場所を今の中点の下へ運び、 間隔の比だけ倍率を変える
// soft = true (= 指) の時は、 範囲を越えた分を抵抗付きで見せる (= 越えられるが重い)。
// soft = false (= マウス) の時は、 範囲で止める。
export function dragTo(start, geom, from, to, { soft = false } = {}) {
  if (from.length < 1 || to.length !== from.length) return soft ? start : clampView(start, geom)
  let raw
  if (from.length === 1) {
    raw = { zoom: start.zoom, x: start.x + (to[0].x - from[0].x), y: start.y + (to[0].y - from[0].y) }
  } else {
    const a = span(from[0], from[1])
    const b = span(to[0], to[1])
    const wanted = a.distance > 0 && b.distance > 0 ? start.zoom * (b.distance / a.distance) : start.zoom
    const zoom = soft ? resistZoom(wanted, geom) : clampZoom(wanted, geom)
    const ratio = zoom / start.zoom
    raw = { zoom, x: b.x - (a.x - start.x) * ratio, y: b.y - (a.y - start.y) * ratio }
  }
  if (!soft) return clampView(raw, geom)
  const range = panRange(raw.zoom, geom)
  return { zoom: raw.zoom, x: resistPan(raw.x, range.x), y: resistPan(raw.y, range.y) }
}

// Safari が trackpad のピンチを伝える出来事 (= gesturestart / gesturechange) を、 指 2 本の形に直す。
// 出来事が持つのは中心 point と、 始まりを 1 とした倍率 scale。 中心を挟んで間隔が scale に比例する
// 2 点にすれば、 指 2 本と同じ計算 (= dragTo) がそのまま使える。
export function gestureTouches(point, scale) {
  const half = (Number.isFinite(scale) && scale > 0 ? scale : 1) / 2
  return [{ x: point.x - half, y: point.y }, { x: point.x + half, y: point.y }]
}

// Ctrl / ⌘ を押しながらの wheel 1 回ぶんの倍率 (= 1 より大きければ拡大)。
export function wheelZoomFactor({ deltaY, deltaMode, ctrlKey }) {
  const perUnit = deltaMode === 1 ? WHEEL_ZOOM_PER_LINE : deltaMode ? WHEEL_ZOOM_PER_PAGE : WHEEL_ZOOM_PER_PIXEL
  return 2 ** (-deltaY * perUnit * (ctrlKey ? WHEEL_ZOOM_PINCH_GAIN : 1))
}

// 素の wheel 1 回ぶんの送り量 (px)。
export function wheelPanDelta({ deltaX, deltaY, deltaMode }, geom) {
  const unit = deltaMode === 1 ? WHEEL_LINE_PX : deltaMode ? geom.frameHeight : 1
  return { x: deltaX * unit, y: deltaY * unit }
}

// ---- 指の速さ ----
//
// tracker = { t, x, y, vx, vy, movedAt }
//   t, x, y : 最後に印を付けた時刻と位置
//   vx, vy  : そこで測った速さ (px / ms)
//   movedAt : 指が最後に動いた時刻

export function startVelocity(point, t) {
  return { t, x: point.x, y: point.y, vx: 0, vy: 0, movedAt: t }
}

// 指が動くたびに呼ぶ。 印から VELOCITY_SAMPLE_MS 経っていたら、 速さを測り直して印を進める。
export function trackVelocity(tracker, point, t) {
  const dt = t - tracker.t
  if (dt < VELOCITY_SAMPLE_MS) return { ...tracker, movedAt: t }
  return { t, x: point.x, y: point.y, vx: (point.x - tracker.x) / dt, vy: (point.y - tracker.y) / dt, movedAt: t }
}

// 指を離した時の速さ (= 最後の印からここまでの動きで測り直す)。
// 指が VELOCITY_SAMPLE_MS 以上動かずに離れたら 0 (= 止めてから離した。 PhotoSwipe は画面の更新ごとに
// 印を進めるので、 止めている間に印が指に追い付いて同じ結果になる。 ここは指が動いた時にしか
// 測らないので、 止まっていた事を別に見る)。
export function releaseVelocity(tracker, point, t) {
  if (t - tracker.movedAt >= VELOCITY_SAMPLE_MS) return { x: 0, y: 0 }
  const dt = t - tracker.t
  if (!(dt > 0)) return { x: tracker.vx, y: tracker.vy }
  return { x: (point.x - tracker.x) / dt, y: (point.y - tracker.y) / dt }
}

// ---- 時間で進む動き ----

// 3 次ベジェの緩急 (= CSS の cubic-bezier(x1, y1, x2, y2) と同じ)。 p は 0〜1 の経過。
export function cubicBezier([x1, y1, x2, y2], p) {
  if (p <= 0) return 0
  if (p >= 1) return 1
  const curve = (a, b, t) => 3 * a * t * (1 - t) ** 2 + 3 * b * t * t * (1 - t) + t ** 3
  // x(t) = p になる t を二分法で求める (= x は単調)
  let lo = 0
  let hi = 1
  for (let i = 0; i < 40; i++) {
    const mid = (lo + hi) / 2
    if (curve(x1, x2, mid) < p) lo = mid
    else hi = mid
  }
  return curve(y1, y2, (lo + hi) / 2)
}

// 速さ v (px / ms) で離した時に、 惰性で滑る距離 (= PhotoSwipe の project)。
export function glideDistance(velocity) {
  return velocity * DECELERATION_RATE / (1 - DECELERATION_RATE)
}

// ばねで end へ向かう値の、 始まってから ms 後の end からのずれ。
//   offset   : 始まりのずれ (= start - end)
//   velocity : 始まりの速さ (px / ms)
//   damping  : 減衰比 (= 1 で行き過ぎない、 1 未満で行き過ぎて戻る)
export function springOffset(offset, velocity, damping, frequency, ms) {
  const t = ms / 1000
  const v = velocity * 1000
  const decay = Math.exp(-damping * frequency * t)
  if (damping >= 1) {
    return (offset + (v + frequency * offset) * t) * decay
  }
  const damped = frequency * Math.sqrt(1 - damping * damping)
  const coeff = (damping * frequency * offset + v) / damped
  return decay * (offset * Math.cos(damped * t) + coeff * Math.sin(damped * t))
}

// ばねの揺れが REST_PX より小さくなるまでの時間 (ms)。 これ以後は止まったものとして扱う。
export function springDuration(offset, velocity, damping, frequency) {
  const v = velocity * 1000
  for (let ms = 0; ms <= 5000; ms += 10) {
    const t = ms / 1000
    const decay = Math.exp(-damping * frequency * t)
    // 以後の揺れの大きさの上限 (= 包絡線)
    const bound = damping >= 1
      ? (Math.abs(offset) + Math.abs(v + frequency * offset) * t) * decay
      : (() => {
        const damped = frequency * Math.sqrt(1 - damping * damping)
        return Math.hypot(offset, (damping * frequency * offset + v) / damped) * decay
      })()
    if (bound < REST_PX) return ms
  }
  return 5000
}

// 1 つの軸で、 指を離した後の動きを決める (= PhotoSwipe の _finishPanGestureForAxis)。
// 惰性で滑った先を範囲に収めた所へ、 離した時の速さを持ったばねで向かう。
// 滑った先が範囲の外なら、 少し行き過ぎてから端へ戻る。 動かないなら null。
function axisSpring(position, velocity, range) {
  const projected = position + glideDistance(velocity)
  const end = clamp(projected, range[0], range[1])
  if (Math.abs(end - position) < REST_PX && Math.abs(glideDistance(velocity)) < REST_PX) return null
  const damping = end === projected ? SPRING_DAMPING_SETTLE : SPRING_DAMPING_OVERSHOOT
  return { start: position, end, velocity, damping, duration: springDuration(position - end, velocity, damping, SPRING_FREQUENCY) }
}

const springAt = (s, fallback, ms) => (
  s ? (ms >= s.duration ? s.end : s.end + springOffset(s.start - s.end, s.velocity, s.damping, SPRING_FREQUENCY, ms)) : fallback
)

// 範囲を越えた拡大・縮小からの戻りの、 経過 (0〜1)。 行き過ぎないばね。
function correctionProgress(ms) {
  return 1 - springOffset(1, 0, 1, CORRECTION_FREQUENCY, ms)
}
const CORRECTION_MS = springDuration(1000, 0, 1, CORRECTION_FREQUENCY)

// ---- 状態と、 入力ごとの移り方 ----
//
//   state = { view, grab, motion }
//     view   : 拡大の状態 (= 真値。 動いている間は、 動きが始まった時の値)
//     grab   : 触れている間だけ在る基準 = { view, from, soft }
//     motion : 指を離した後の動き。 無ければ null
//       { kind: 'tween',   from, to, start }            ダブルタップの拡大・戻り
//       { kind: 'correct', from, to, start }            範囲を越えた拡大・縮小からの戻り
//       { kind: 'glide',   zoom, x, y, start, to }      惰性と端からの戻り (= x / y は軸ごとのばね)
export const INITIAL_ZOOM_STATE = Object.freeze({ view: FIT_VIEW, grab: null, motion: null })

// 動きの行き先。
const motionEnd = (motion) => motion.to

// 動きが終わる時刻 (= motion.start からの ms)。
function motionDuration(motion) {
  if (motion.kind === 'tween') return ZOOM_ANIMATION_MS
  if (motion.kind === 'correct') return CORRECTION_MS
  return Math.max(motion.x ? motion.x.duration : 0, motion.y ? motion.y.duration : 0)
}

export function motionDone(state, now) {
  return !state.motion || now - state.motion.start >= motionDuration(state.motion)
}

// 時刻 now に画面へ出す view。
export function viewAt(state, geom, now) {
  const { motion } = state
  if (!motion) return state.grab && state.grab.soft ? state.view : clampView(state.view, geom)
  const ms = Math.max(0, now - motion.start)
  if (ms >= motionDuration(motion)) return motionEnd(motion)
  if (motion.kind === 'glide') {
    return { zoom: motion.zoom, x: springAt(motion.x, motion.to.x, ms), y: springAt(motion.y, motion.to.y, ms) }
  }
  const p = motion.kind === 'tween' ? cubicBezier(ZOOM_EASING, ms / ZOOM_ANIMATION_MS) : correctionProgress(ms)
  return {
    zoom: lerp(motion.from.zoom, motion.to.zoom, p),
    x: lerp(motion.from.x, motion.to.x, p),
    y: lerp(motion.from.y, motion.to.y, p),
  }
}

// 動きが済んだ後に落ち着く view (= 動いていなければ今の view)。 「今は合わせか」 はこれで決める
// (= 拡大の途中でもう一度ダブルタップしたら、 行き先から見て合わせへ戻る)。
export function restView(state, geom) {
  return state.motion ? motionEnd(state.motion) : clampView(state.view, geom)
}

// 指を離した時の動き。 範囲を越えた倍率なら範囲へ戻し、 そうでなければ惰性で滑らせる。
function releaseMotion(view, geom, velocity, center, now) {
  const zoom = clampZoom(view.zoom, geom)
  if (Math.abs(zoom - view.zoom) > ZOOM_EPSILON) {
    // 指の中点の下の場所を保ったまま、 範囲の端の倍率へ
    const ratio = zoom / view.zoom
    const to = clampView({ zoom, x: center.x - (center.x - view.x) * ratio, y: center.y - (center.y - view.y) * ratio }, geom)
    return { kind: 'correct', from: view, to, start: now }
  }
  const range = panRange(view.zoom, geom)
  const x = axisSpring(view.x, velocity.x, range.x)
  const y = axisSpring(view.y, velocity.y, range.y)
  if (!x && !y) return null
  const to = { zoom: view.zoom, x: x ? x.end : clamp(view.x, range.x[0], range.x[1]), y: y ? y.end : clamp(view.y, range.y[0], range.y[1]) }
  return { kind: 'glide', zoom: view.zoom, x, y, start: now, to }
}

// action (= どれも geom と now を持つ):
//   { type: 'grab', touches, soft }                 触れている指の本数が変わった (= 1 本以上)
//   { type: 'move', touches }                       指が動いた
//   { type: 'release', velocity, center }           最後の指が離れた (= velocity は px / ms)
//   { type: 'wheel-zoom', point, factor }
//   { type: 'wheel-pan', dx, dy }
//   { type: 'toggle', point, animate }              ダブルタップ / ダブルクリック
//   { type: 'settle' }                              動きが終わった
export function reduceZoom(state, action) {
  const { geom, now = 0 } = action
  // 今、 画面に出ている view (= 動きの途中なら途中の値)。 どの入力もここから続ける。
  const shown = () => viewAt(state, geom, now)
  switch (action.type) {
    case 'grab': {
      if (!action.touches.length) return { view: shown(), grab: null, motion: null }
      const soft = !!action.soft
      const view = soft ? shown() : clampView(shown(), geom)
      // 2 本 → 1 本に減った時に倍率が範囲の外なら、 残った指では掴まずに範囲へ戻す
      // (= PhotoSwipe と同じ。 残った指で動かすと、 範囲の外の倍率のまま移動になる)
      if (soft && state.grab && state.grab.from.length > action.touches.length
        && Math.abs(clampZoom(view.zoom, geom) - view.zoom) > ZOOM_EPSILON) {
        const center = span(state.grab.to[0], state.grab.to[1] || state.grab.to[0])
        return { view, grab: null, motion: releaseMotion(view, geom, { x: 0, y: 0 }, center, now) }
      }
      return { view, grab: { view, from: action.touches, to: action.touches, soft }, motion: null }
    }
    case 'move': {
      if (!state.grab || action.touches.length !== state.grab.from.length) return state
      const view = dragTo(state.grab.view, geom, state.grab.from, action.touches, { soft: state.grab.soft })
      return { view, grab: { ...state.grab, to: action.touches }, motion: null }
    }
    case 'release': {
      if (!state.grab) return state
      const view = state.grab.soft ? state.view : clampView(state.view, geom)
      if (!state.grab.soft) return { view, grab: null, motion: null }
      const to = state.grab.to
      const center = action.center || span(to[0], to[1] || to[0])
      // 2 本で終わった時は滑らせない (= ピンチの終わりに画像が流れない)
      const velocity = to.length === 1 && action.velocity ? action.velocity : { x: 0, y: 0 }
      return { view, grab: null, motion: releaseMotion(view, geom, velocity, center, now) }
    }
    // 掴んでいる最中・動いている最中に別の入力で view が変わったら、 基準も動きも捨てる
    // (= 残すと、 次に指が動いた時や動きの続きで、 古い値へ引き戻される)
    case 'wheel-zoom': {
      const base = clampView(shown(), geom)
      return { view: zoomAt(base, geom, action.point, base.zoom * action.factor), grab: null, motion: null }
    }
    case 'wheel-pan':
      return { view: panBy(shown(), geom, action.dx, action.dy), grab: null, motion: null }
    case 'toggle': {
      const from = shown()
      const to = toggleZoomAt(restView(state, geom), geom, action.point)
      if (!action.animate) return { view: to, grab: null, motion: null }
      return { view: from, grab: null, motion: { kind: 'tween', from, to, start: now } }
    }
    case 'settle':
      return state.motion ? { view: motionEnd(state.motion), grab: state.grab, motion: null } : state
    default:
      return state
  }
}
