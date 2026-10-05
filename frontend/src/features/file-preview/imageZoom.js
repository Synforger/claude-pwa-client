// 画像プレビューの拡大と移動の計算 (= 画面から切り離した純関数。 DOM には触らない)。
//
// 座標は「枠」 (= 画像を見せる領域) の左上を原点にした px。
//   view = { zoom, x, y }
//     zoom : 「合わせ」 を 1 とした倍率 (= 合わせ = 枠の幅に収めた大きさ。 枠より小さい画像は等倍のまま)
//     x, y : 画像の左上の位置
//   geom = { naturalWidth, naturalHeight, frameWidth, frameHeight }
//
// 拡大の状態はこの view 1 つだけで、 画面に出す大きさと位置は clampView(view, geom) から導く
// (= 枠の大きさが変わっても、 合わせは zoom = 1 のまま合わせで居続ける)。
//
// 指やドラッグの動きは、 触れ始めた時の view と指の位置 (= grab) を基準に、 今の指の位置から
// 直に求める (= 途中の経路に依らない。 端で止まった分の誤差が積もらない)。

// 拡大の上限 (= 画像の 1 画素を、 画面の何点ぶんまで大きくできるか)。
// 無いと、 指を広げ続けるだけで画像が際限なく大きくなり、 どこを見ているか分からなくなる。
export const MAX_PIXEL_SCALE = 8

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

export const FIT_VIEW = Object.freeze({ zoom: 1, x: 0, y: 0 })

const clamp = (value, min, max) => Math.min(Math.max(value, min), max)

// 合わせの時に、 画像の 1 画素が画面の何点になるか (= 幅に収める。 拡大はしない)。
export function fitScale(geom) {
  const { naturalWidth, frameWidth } = geom
  if (!(naturalWidth > 0) || !(frameWidth > 0)) return 1
  return Math.min(1, frameWidth / naturalWidth)
}

// 等倍 (= 画像の 1 画素が画面の 1 点) になる zoom。
export function actualSizeZoom(geom) {
  return 1 / fitScale(geom)
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

// 位置を、 画像が枠の外へ出て行かない範囲に収める。
//   横: 枠より狭ければ中央、 広ければ枠を覆う範囲
//   縦: 枠より低ければ上端、 高ければ枠を覆う範囲 (= 合わせで縦に長い画像は、 この範囲を送って読む)
export function clampView(view, geom) {
  const zoom = clampZoom(view.zoom, geom)
  const { width, height } = shownSize(zoom, geom)
  const { frameWidth, frameHeight } = geom
  const x = width <= frameWidth
    ? (frameWidth - width) / 2
    : clamp(Number.isFinite(view.x) ? view.x : 0, frameWidth - width, 0)
  const y = height <= frameHeight
    ? 0
    : clamp(Number.isFinite(view.y) ? view.y : 0, frameHeight - height, 0)
  return { zoom, x, y }
}

// 画像を (dx, dy) だけ動かす。
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

// ダブルタップ / ダブルクリック: 合わせの時は point を中心に等倍へ、 それ以外は合わせへ戻す。
// 等倍が合わせより大きくならない小さい画像では、 上限まで拡大する。
export function toggleZoomAt(view, geom, point) {
  const base = clampView(view, geom)
  if (!isFit(base)) return clampView(FIT_VIEW, geom)
  const actual = actualSizeZoom(geom)
  const target = actual > 1 + ZOOM_EPSILON ? actual : maxZoom(geom)
  return zoomAt(base, geom, point, target)
}

// 2 点の中点と間隔
export function span(a, b) {
  return { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2, distance: Math.hypot(a.x - b.x, a.y - b.y) }
}

// 指 (= またはドラッグ中のマウス) が from の位置から to の位置へ動いた時の view。
// start は触れ始めた時の view、 from / to は同じ順に並んだ点の配列。
//   1 点: 動いた分だけ画像を動かす (= 指の下の場所が指に付いて来る)
//   2 点: 中点の下に在った場所を今の中点の下へ運び、 間隔の比だけ倍率を変える
export function dragTo(start, geom, from, to) {
  const base = clampView(start, geom)
  if (from.length < 1 || to.length !== from.length) return base
  if (from.length === 1) {
    return clampView({ zoom: base.zoom, x: base.x + (to[0].x - from[0].x), y: base.y + (to[0].y - from[0].y) }, geom)
  }
  const a = span(from[0], from[1])
  const b = span(to[0], to[1])
  const zoom = a.distance > 0 && b.distance > 0 ? clampZoom(base.zoom * (b.distance / a.distance), geom) : base.zoom
  const ratio = zoom / base.zoom
  return clampView({
    zoom,
    x: b.x - (a.x - base.x) * ratio,
    y: b.y - (a.y - base.y) * ratio,
  }, geom)
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

// ---- 状態と、 入力ごとの移り方 ----
//
//   state = { view, grab }
//     view : 拡大の状態 (= 真値)
//     grab : 触れている間だけ在る基準 = { view: 触れ始めた時の view, from: その時の指の位置 }
export const INITIAL_ZOOM_STATE = Object.freeze({ view: FIT_VIEW, grab: null })

// action (= どれも geom を持つ):
//   { type: 'grab', touches }        触れている指の本数が変わった (= 0 本なら離した)
//   { type: 'move', touches }        指が動いた
//   { type: 'wheel-zoom', point, factor }
//   { type: 'wheel-pan', dx, dy }
//   { type: 'toggle', point }        ダブルタップ / ダブルクリック
export function reduceZoom(state, action) {
  const { geom } = action
  switch (action.type) {
    case 'grab': {
      const view = clampView(state.view, geom)
      return { view, grab: action.touches.length ? { view, from: action.touches } : null }
    }
    case 'move': {
      if (!state.grab || action.touches.length !== state.grab.from.length) return state
      return { view: dragTo(state.grab.view, geom, state.grab.from, action.touches), grab: state.grab }
    }
    // 指で掴んでいる最中に別の入力で view が変わったら、 掴んだ時の基準は捨てる
    // (= 残すと、 次に指が動いた時に古い基準へ引き戻される)
    case 'wheel-zoom':
      return { view: zoomAt(state.view, geom, action.point, clampView(state.view, geom).zoom * action.factor), grab: null }
    case 'wheel-pan':
      return { view: panBy(state.view, geom, action.dx, action.dy), grab: null }
    case 'toggle':
      return { view: toggleZoomAt(state.view, geom, action.point), grab: null }
    default:
      return state
  }
}
