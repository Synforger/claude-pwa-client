import { useEffect, useReducer, useRef, useState } from 'react'
import {
  INITIAL_ZOOM_STATE,
  reduceZoom,
  viewAt,
  motionDone,
  shownSize,
  wheelZoomFactor,
  wheelPanDelta,
  gestureTouches,
  startVelocity,
  trackVelocity,
  releaseVelocity,
} from './imageZoom.js'

// 拡大して見られる画像 1 枚 (= file のプレビュー用)。
//
// 拡大の状態は 1 つ (= imageZoom.js の state) で、 画面に出す大きさと位置は毎回そこから導く。
// 計算は imageZoom.js の純関数が持ち、 ここは入力 (= 指 / マウス / wheel) と時刻を計算へ渡すだけ。
//   - 指 2 本: 中点を中心に拡大・縮小 (= 範囲を越えた分は重く、 離すと戻る)
//   - 指 1 本: 移動 (= 離すと惰性で滑り、 端では少し行き過ぎて戻る)
//   - ダブルタップ / ダブルクリック: 合わせ ⇄ 一段拡大 (= 滑らかに動く)
//   - マウスのドラッグ: 移動 (= 範囲で止まる、 惰性なし)
//   - Ctrl か ⌘ を押しながらの wheel: カーソルの位置を中心に拡大・縮小 / 素の wheel: 送り
//   - trackpad のピンチ: Chromium / Firefox は Ctrl 付きの wheel として、 Safari は gesture の出来事として届く
// 別の画像へ切り替えた時に合わせへ戻すのは呼ぶ側 (= src を key にして作り直す)。
export default function ZoomableImage({ src, alt, onLoad, onError }) {
  const frameRef = useRef(null)
  const [state, dispatch] = useReducer(reduceZoom, INITIAL_ZOOM_STATE)
  // 動きの途中を描くための時刻 (= 動いている間だけ、 画面の更新ごとに進める)
  const [clock, setClock] = useState(0)
  // 測った大きさ (= 計算への入力。 拡大の状態ではない)
  const [natural, setNatural] = useState(null)
  const [frame, setFrame] = useState(null)
  // 触れている指 / 押しているボタンの今の位置 (= 触れた順。 計算へ渡す入力の控え)
  const pointersRef = useRef(new Map())
  // 1 本指の速さの控え (= 離した時の惰性に使う)
  const velocityRef = useRef(null)

  const geom = natural && frame
    ? { naturalWidth: natural.width, naturalHeight: natural.height, frameWidth: frame.width, frameHeight: frame.height }
    : null

  useEffect(() => {
    const el = frameRef.current
    if (!el) return undefined
    const measure = () => setFrame(prev => (
      prev && prev.width === el.clientWidth && prev.height === el.clientHeight
        ? prev
        : { width: el.clientWidth, height: el.clientHeight }
    ))
    measure()
    if (typeof ResizeObserver === 'undefined') return undefined
    const observer = new ResizeObserver(measure)
    observer.observe(el)
    return () => observer.disconnect()
  }, [])

  // 動いている間だけ、 画面の更新ごとに時刻を進めて描き直す。 終わったら行き先を状態に確定する。
  const { motion } = state
  useEffect(() => {
    if (!motion || !natural || !frame) return undefined
    const g = { naturalWidth: natural.width, naturalHeight: natural.height, frameWidth: frame.width, frameHeight: frame.height }
    let id = requestAnimationFrame(function step() {
      const now = performance.now()
      if (motionDone({ motion }, now)) {
        dispatch({ type: 'settle', geom: g, now })
        return
      }
      setClock(now)
      id = requestAnimationFrame(step)
    })
    return () => cancelAnimationFrame(id)
  }, [motion, natural, frame])

  // 指の速さは、 出来事が起きた時刻 (= e.timeStamp) の差で測る。 処理した時刻で測ると、 画面が
  // 忙しくて出来事がまとめて届いた時に間隔が詰まり、 速さが何倍にも出て画像が飛ぶ。
  const eventTime = (e) => (e.timeStamp > 0 ? e.timeStamp : performance.now())

  // 枠の左上を原点にした位置
  const pointIn = (e) => {
    const rect = frameRef.current.getBoundingClientRect()
    return { x: e.clientX - rect.left, y: e.clientY - rect.top }
  }

  // wheel と gesture は preventDefault が要る (= ブラウザ自体が拡大するのを止める) ので、
  // listener を直に付ける (= React の onWheel は passive で、 gesture は React が扱わない)。
  // 付け直すのは測った大きさが変わった時だけ。
  useEffect(() => {
    const el = frameRef.current
    if (!el || !natural || !frame) return undefined
    const g = { naturalWidth: natural.width, naturalHeight: natural.height, frameWidth: frame.width, frameHeight: frame.height }
    const onWheel = (e) => {
      e.preventDefault()
      const now = performance.now()
      if (e.ctrlKey || e.metaKey) {
        dispatch({ type: 'wheel-zoom', geom: g, now, point: pointIn(e), factor: wheelZoomFactor(e) })
      } else {
        const delta = wheelPanDelta(e, g)
        dispatch({ type: 'wheel-pan', geom: g, now, dx: -delta.x, dy: -delta.y })
      }
    }
    // Safari は trackpad のピンチを wheel ではなく gesture の出来事で伝える (= 中心と、 始まりを 1 とした倍率)。
    // 指 2 本の形に直して同じ計算へ渡す (= PC の入力なので、 範囲で止める)。 iOS では指のピンチでも
    // 同じ出来事が出るので、 指が触れている間は pointer の側に任せて、 ここでは何もしない。
    const onGesture = (e) => {
      e.preventDefault()
      if (pointersRef.current.size > 0) return
      const now = performance.now()
      if (e.type === 'gestureend') {
        dispatch({ type: 'release', geom: g, now })
      } else {
        dispatch({
          type: e.type === 'gesturestart' ? 'grab' : 'move',
          geom: g, now, soft: false, touches: gestureTouches(pointIn(e), e.scale),
        })
      }
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    el.addEventListener('gesturestart', onGesture)
    el.addEventListener('gesturechange', onGesture)
    el.addEventListener('gestureend', onGesture)
    return () => {
      el.removeEventListener('wheel', onWheel)
      el.removeEventListener('gesturestart', onGesture)
      el.removeEventListener('gesturechange', onGesture)
      el.removeEventListener('gestureend', onGesture)
    }
  }, [natural, frame])

  const touches = () => [...pointersRef.current.values()]

  const handlePointerDown = (e) => {
    if (e.pointerType === 'mouse' && e.button !== 0) return
    const point = pointIn(e)
    const now = performance.now()
    pointersRef.current.set(e.pointerId, point)
    // 枠の外へ出ても move / up を受け続ける。 合成された pointer (= 実在しない id) では投げるので握る
    try { e.currentTarget.setPointerCapture(e.pointerId) } catch { /* 捕まえられなくても枠の中では動く */ }
    velocityRef.current = pointersRef.current.size === 1 ? startVelocity(point, eventTime(e)) : null
    // 指は範囲を越えて引ける (= 重く、 離すと戻る)。 マウスは範囲で止める
    if (geom) dispatch({ type: 'grab', geom, now, soft: e.pointerType !== 'mouse', touches: touches() })
  }

  const handlePointerMove = (e) => {
    if (!pointersRef.current.has(e.pointerId)) return
    const point = pointIn(e)
    const now = performance.now()
    pointersRef.current.set(e.pointerId, point)
    if (velocityRef.current && pointersRef.current.size === 1) {
      velocityRef.current = trackVelocity(velocityRef.current, point, eventTime(e))
    }
    if (geom) dispatch({ type: 'move', geom, now, touches: touches() })
  }

  const handlePointerEnd = (e) => {
    if (!pointersRef.current.has(e.pointerId)) return
    const point = pointIn(e)
    const now = performance.now()
    const wasSingle = pointersRef.current.size === 1
    pointersRef.current.delete(e.pointerId)
    if (!geom) return
    if (pointersRef.current.size === 0) {
      const velocity = wasSingle && velocityRef.current && e.type !== 'pointercancel'
        ? releaseVelocity(velocityRef.current, point, eventTime(e))
        : null
      velocityRef.current = null
      dispatch({ type: 'release', geom, now, velocity })
    } else {
      // 残った指で続ける (= 残った指の今の位置が新しい基準)
      const rest = touches()
      velocityRef.current = rest.length === 1 ? startVelocity(rest[0], eventTime(e)) : null
      dispatch({ type: 'grab', geom, now, soft: e.pointerType !== 'mouse', touches: rest })
    }
  }

  const handleDoubleClick = (e) => {
    if (geom) dispatch({ type: 'toggle', geom, now: performance.now(), point: pointIn(e), animate: true })
  }

  // 動いている間は clock (= 画面の更新ごとに進む) の時点、 止まっている時は状態そのまま
  const shown = geom ? viewAt(state, geom, motion ? Math.max(clock, motion.start) : 0) : null
  const size = shown ? shownSize(shown.zoom, geom) : null

  return (
    <div
      ref={frameRef}
      className="file-image-frame"
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={handlePointerEnd}
      onPointerCancel={handlePointerEnd}
      onDoubleClick={handleDoubleClick}
      data-testid="file-preview-image-frame"
    >
      <img
        className="file-image"
        src={src}
        alt={alt}
        draggable={false}
        // 大きさが測れるまでは見せない (= 等倍のまま一瞬出て、 合わせへ縮むのを見せない)
        style={shown
          ? { width: `${size.width}px`, height: `${size.height}px`, transform: `translate(${shown.x}px, ${shown.y}px)` }
          : { visibility: 'hidden' }}
        onLoad={(e) => {
          setNatural({ width: e.currentTarget.naturalWidth, height: e.currentTarget.naturalHeight })
          onLoad?.()
        }}
        onError={onError}
        data-testid="file-preview-image"
      />
    </div>
  )
}
