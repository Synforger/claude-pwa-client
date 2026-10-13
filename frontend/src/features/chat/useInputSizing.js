// 入力欄の大きさを DOM で測って決める hook (= 計算そのものは inputSizing.js)。
//
//   - 畳んだ時: text が変わるたびに textarea の高さを中身に合わせ、 上限で止める
//   - 広げた時: 入力欄を「今 見えている範囲」 に固定し、 画面キーボードの出入り / 回転 / 窓の大きさに追従する
import { useCallback, useEffect, useLayoutEffect, useState } from 'react'
import { collapsedCap, fitHeight, expandedRect } from './inputSizing.js'

const px = (v) => parseFloat(v) || 0
// line-height が数で決まっていない (= normal) 時に使う、 文字の大きさに対する倍率 (= ブラウザの既定に近い値)
const NORMAL_LINE_HEIGHT = 1.2

// textarea の高さを中身に合わせ、 上限を超えているかを返す。
function fitTextarea(el) {
  const cs = getComputedStyle(el)
  const borderY = px(cs.borderTopWidth) + px(cs.borderBottomWidth)
  const cap = collapsedCap({
    lineHeight: px(cs.lineHeight) || px(cs.fontSize) * NORMAL_LINE_HEIGHT,
    padY: px(cs.paddingTop) + px(cs.paddingBottom),
    borderY,
  })
  // 高さの指定を外して測る (= 外さないと、 前回の指定が「中身の高さ」 として返ってくる)
  el.style.height = ''
  const { height, overflowing } = fitHeight({
    content: el.scrollHeight + borderY,
    natural: el.offsetHeight,
    cap,
  })
  if (height != null) el.style.height = `${height}px`
  return overflowing
}

// 見えている範囲 (= 画面キーボードを除いた部分)。 visualViewport の無い環境では窓全体。
function visibleRange() {
  const vv = window.visualViewport
  return vv ? { top: vv.offsetTop, height: vv.height } : { top: 0, height: window.innerHeight }
}

export function useInputSizing({ text, slotRef, areaRef, textareaRef }) {
  const [expanded, setExpanded] = useState(false)
  const [overflowing, setOverflowing] = useState(false)
  const [rect, setRect] = useState(null)
  // 広げている間、 入力欄が流れの中で占めていた高さ (= 上のメッセージ一覧を動かさないための場所取り)
  const [slotHeight, setSlotHeight] = useState(null)

  // 畳んだ時: 中身に合わせる。 広げている間は CSS が高さを決めるので、 指定を外すだけ。
  useLayoutEffect(() => {
    const el = textareaRef.current
    if (!el) return
    if (expanded) { el.style.height = ''; return }
    setOverflowing(fitTextarea(el))
  }, [text, expanded, textareaRef])

  // 幅が変わると折り返しが変わるので、 畳んだ時の高さを取り直す (= 回転 / 窓の大きさ / 横の drawer)
  useEffect(() => {
    const el = textareaRef.current
    if (!el || expanded || typeof ResizeObserver === 'undefined') return
    let width = el.offsetWidth
    const ro = new ResizeObserver(() => {
      if (el.offsetWidth === width) return
      width = el.offsetWidth
      setOverflowing(fitTextarea(el))
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [expanded, textareaRef])

  // 広げた時: 見えている範囲に合わせて矩形を決め、 範囲が変わるたびに取り直す。
  useLayoutEffect(() => {
    if (!expanded) { setRect(null); return }
    const update = () => {
      const slot = slotRef.current
      if (!slot) return
      const s = slot.getBoundingClientRect()
      // チャットの領域の上端 = この入力欄が居る chat panel の先頭の要素 (= メッセージ一覧) の上端
      const head = slot.closest('.cpc-chat-panel')?.firstElementChild
      const areaTop = head ? head.getBoundingClientRect().top : 0
      setRect(expandedRect({
        areaTop,
        slot: { left: s.left, width: s.width, bottom: s.bottom, height: s.height },
        viewport: visibleRange(),
      }))
    }
    update()
    const vv = window.visualViewport
    vv?.addEventListener('resize', update)
    vv?.addEventListener('scroll', update)
    window.addEventListener('resize', update)
    return () => {
      vv?.removeEventListener('resize', update)
      vv?.removeEventListener('scroll', update)
      window.removeEventListener('resize', update)
    }
  }, [expanded, slotRef])

  const expand = useCallback(() => {
    // 流れから外す前に、 今の高さを場所取りとして控える
    setSlotHeight(areaRef.current ? areaRef.current.offsetHeight : null)
    setExpanded(true)
  }, [areaRef])
  const collapse = useCallback(() => setExpanded(false), [])

  return {
    expanded,
    // 開閉のボタンは、 隠れている分が在る時と、 広げている時にだけ意味を持つ
    showToggle: expanded || overflowing,
    expand,
    collapse,
    slotStyle: expanded && slotHeight != null ? { height: `${slotHeight}px` } : undefined,
    areaStyle: expanded && rect
      ? { top: `${rect.top}px`, left: `${rect.left}px`, width: `${rect.width}px`, height: `${rect.height}px` }
      : undefined,
  }
}
