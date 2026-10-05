import { useEffect, useReducer, useRef, useState } from 'react'
import {
  INITIAL_ZOOM_STATE,
  reduceZoom,
  clampView,
  shownSize,
  wheelZoomFactor,
  wheelPanDelta,
} from './imageZoom.js'

// 拡大して見られる画像 1 枚 (= file のプレビュー用)。
//
// 拡大の状態は view (= 倍率と位置) 1 つだけで、 画面に出す大きさと位置は毎回そこから導く。
// 計算は imageZoom.js の純関数が持ち、 ここは入力 (= 指 / マウス / wheel) を計算へ渡すだけ。
//   - 指 2 本: 中点を中心に拡大・縮小 / 指 1 本・ドラッグ: 移動
//   - Ctrl か ⌘ を押しながらの wheel: カーソルの位置を中心に拡大・縮小 / 素の wheel: 送り
//   - ダブルタップ / ダブルクリック: 合わせ ⇄ 等倍
// 別の画像へ切り替えた時に合わせへ戻すのは呼ぶ側 (= src を key にして作り直す)。
export default function ZoomableImage({ src, alt, onLoad, onError }) {
  const frameRef = useRef(null)
  const [{ view }, dispatch] = useReducer(reduceZoom, INITIAL_ZOOM_STATE)
  // 測った大きさ (= 計算への入力。 拡大の状態ではない)
  const [natural, setNatural] = useState(null)
  const [frame, setFrame] = useState(null)
  // 触れている指 / 押しているボタンの今の位置 (= 触れた順。 計算へ渡す入力の控え)
  const pointersRef = useRef(new Map())

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

  // 枠の左上を原点にした位置
  const pointIn = (e) => {
    const rect = frameRef.current.getBoundingClientRect()
    return { x: e.clientX - rect.left, y: e.clientY - rect.top }
  }

  // wheel は preventDefault が要る (= Ctrl + wheel でブラウザ自体が拡大するのを止める) ので、
  // passive でない listener を直に付ける (= React の onWheel は passive)。 付け直すのは測った大きさが変わった時だけ。
  useEffect(() => {
    const el = frameRef.current
    if (!el || !natural || !frame) return undefined
    const g = { naturalWidth: natural.width, naturalHeight: natural.height, frameWidth: frame.width, frameHeight: frame.height }
    const onWheel = (e) => {
      e.preventDefault()
      if (e.ctrlKey || e.metaKey) {
        dispatch({ type: 'wheel-zoom', geom: g, point: pointIn(e), factor: wheelZoomFactor(e) })
      } else {
        const delta = wheelPanDelta(e, g)
        dispatch({ type: 'wheel-pan', geom: g, dx: -delta.x, dy: -delta.y })
      }
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  }, [natural, frame])

  const touches = () => [...pointersRef.current.values()]

  const handlePointerDown = (e) => {
    if (e.pointerType === 'mouse' && e.button !== 0) return
    pointersRef.current.set(e.pointerId, pointIn(e))
    // 枠の外へ出ても move / up を受け続ける。 合成された pointer (= 実在しない id) では投げるので握る
    try { e.currentTarget.setPointerCapture(e.pointerId) } catch { /* 捕まえられなくても枠の中では動く */ }
    if (geom) dispatch({ type: 'grab', geom, touches: touches() })
  }

  const handlePointerMove = (e) => {
    if (!pointersRef.current.has(e.pointerId)) return
    pointersRef.current.set(e.pointerId, pointIn(e))
    if (geom) dispatch({ type: 'move', geom, touches: touches() })
  }

  const handlePointerEnd = (e) => {
    if (!pointersRef.current.delete(e.pointerId)) return
    if (geom) dispatch({ type: 'grab', geom, touches: touches() })
  }

  const handleDoubleClick = (e) => {
    if (geom) dispatch({ type: 'toggle', geom, point: pointIn(e) })
  }

  const shown = geom ? clampView(view, geom) : null
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
