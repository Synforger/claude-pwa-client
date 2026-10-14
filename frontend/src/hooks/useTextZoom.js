// 文章の字の大きさを、 2 本の指 / Ctrl・⌘ + ホイール / Mac の Safari のつまむ動きで変える (= 📋 のメモと
// markdown のプレビュー)。 倍率の値と計算は textZoom.js。
//
// frameRef = 送る枠 (= .modal-body)。 指の出来事はここで受け、 倍率を変えた後の送りもここで直す。
// contentRef = 倍率を掛ける本文 (= .md-preview)。 読み込みや切り替えで作り直されるので、 描くたびに
// 今の倍率を当て直す。
//
// 指の途中は React の state を通さず、 本文の style を直に書く (= 動かすたびに markdown を描き直さない)。
// 端末に覚えるのは、 指を離した時とホイールの 1 回ごと。
//
// 表だけは、 どのマスも 1 字まで折っても余白と罫の分の幅が残るので、 列が多いと広げた時に枠に収まらない。
// それ以上折れない表は、 枠の幅に収まる所までその表だけ小さく描く (= 横には送らない、 の決まりを守る)。
// 本文の大きさが変わるたび (= 中身が描かれた / 枠の幅が変わった / 倍率を変えた) に測り直す。
//
// 1 本の指の縦の送りはブラウザに任せる (= touch-action: pan-x pan-y を本文の CSS に書く)。 2 本の指は
// touch の出来事で受ける (= pointer の出来事は、 ブラウザが送りを始めると pointercancel で取り上げられる)。
import { useEffect, useLayoutEffect, useRef } from 'react'
import { clampTextZoom, loadTextZoom, saveTextZoom, scrollToKeep, spread, wheelFactor } from './textZoom.js'

// 本文に倍率を掛ける (= CSS の zoom と、 罫の太さを保つための --text-zoom)
function applyZoom(content, zoom) {
  content.style.zoom = String(zoom)
  content.style.setProperty('--text-zoom', String(zoom))
}

// 枠に収まらない表を、 収まる大きさまで小さく描く (= 表ごとの zoom。 本文の倍率の上に掛かる)
function fitWideTables(content) {
  const width = content.getBoundingClientRect().width
  for (const table of content.querySelectorAll('table')) {
    table.style.zoom = ''
    const tableWidth = table.getBoundingClientRect().width
    if (tableWidth > width + 0.5) table.style.zoom = String(width / tableWidth)
  }
}

export function useTextZoom(frameRef, contentRef) {
  const zoomRef = useRef(null)
  if (zoomRef.current === null) zoomRef.current = loadTextZoom()
  const resizeRef = useRef(null)     // 本文と枠の大きさを見張る ResizeObserver
  const observedRef = useRef(null)   // 見張っている本文の要素

  useLayoutEffect(() => {
    const content = contentRef.current
    if (content) {
      applyZoom(content, zoomRef.current)
      fitWideTables(content)
    }
    const resize = resizeRef.current
    if (resize && observedRef.current !== content) {
      if (observedRef.current) resize.unobserve(observedRef.current)
      if (content) resize.observe(content)
      observedRef.current = content
    }
  })

  useEffect(() => {
    const frame = frameRef.current
    if (!frame) return undefined

    // 中身が後から描かれた (= markdown の描画は遅れて来る) / 枠の幅が変わった時に、 表を測り直す
    const resize = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(() => {
      if (contentRef.current) fitWideTables(contentRef.current)
    })
    if (resize) {
      resize.observe(frame)
      if (contentRef.current) resize.observe(contentRef.current)
    }
    resizeRef.current = resize
    observedRef.current = contentRef.current

    // anchorY = 指 (= カーソル) の在る高さ。 そこに見えていた所が、 変えた後も同じ高さに来るよう送り直す。
    const setZoom = (next, anchorY) => {
      const content = contentRef.current
      if (!content) return
      next = clampTextZoom(next)
      if (next === zoomRef.current) return
      const before = content.getBoundingClientRect()
      zoomRef.current = next
      applyZoom(content, next)
      fitWideTables(content)
      frame.scrollTop += scrollToKeep(before, content.getBoundingClientRect(), anchorY)
    }

    let pinch = null
    const onTouchStart = (event) => {
      if (event.touches.length === 2 && contentRef.current) pinch = { spread: spread(event.touches), zoom: zoomRef.current }
    }
    const onTouchMove = (event) => {
      if (!pinch || event.touches.length !== 2) return
      event.preventDefault()
      setZoom(pinch.zoom * spread(event.touches) / pinch.spread, (event.touches[0].clientY + event.touches[1].clientY) / 2)
    }
    const onTouchEnd = () => {
      if (!pinch) return
      pinch = null
      saveTextZoom(zoomRef.current)
    }
    const onWheel = (event) => {
      if (!event.ctrlKey || !contentRef.current) return
      event.preventDefault()
      setZoom(zoomRef.current * wheelFactor(event.deltaY, event.deltaMode), event.clientY)
      saveTextZoom(zoomRef.current)
    }
    // Mac の Safari のトラックパッドは wheel ではなく gesture の出来事で渡す。 画面に触れる端末では上の
    // touch と重なるので使わない。
    let gestureFrom = null
    const onGestureStart = (event) => {
      if (!contentRef.current) return
      event.preventDefault()
      gestureFrom = zoomRef.current
    }
    const onGestureChange = (event) => {
      if (gestureFrom === null) return
      event.preventDefault()
      setZoom(gestureFrom * event.scale, event.clientY)
    }
    const onGestureEnd = () => {
      if (gestureFrom === null) return
      gestureFrom = null
      saveTextZoom(zoomRef.current)
    }
    const touchScreen = 'ontouchstart' in window

    frame.addEventListener('touchstart', onTouchStart, { passive: true })
    frame.addEventListener('touchmove', onTouchMove, { passive: false })
    frame.addEventListener('touchend', onTouchEnd)
    frame.addEventListener('touchcancel', onTouchEnd)
    frame.addEventListener('wheel', onWheel, { passive: false })
    if (!touchScreen) {
      frame.addEventListener('gesturestart', onGestureStart)
      frame.addEventListener('gesturechange', onGestureChange)
      frame.addEventListener('gestureend', onGestureEnd)
    }
    return () => {
      resize?.disconnect()
      resizeRef.current = null
      observedRef.current = null
      frame.removeEventListener('touchstart', onTouchStart)
      frame.removeEventListener('touchmove', onTouchMove)
      frame.removeEventListener('touchend', onTouchEnd)
      frame.removeEventListener('touchcancel', onTouchEnd)
      frame.removeEventListener('wheel', onWheel)
      if (!touchScreen) {
        frame.removeEventListener('gesturestart', onGestureStart)
        frame.removeEventListener('gesturechange', onGestureChange)
        frame.removeEventListener('gestureend', onGestureEnd)
      }
    }
  }, [frameRef, contentRef])
}
