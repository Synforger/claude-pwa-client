// 入力欄の大きさを DOM で測って決める hook (= 計算そのものは inputSizing.js)。
//
// text が変わるたびに textarea の高さを中身に合わせ、 畳んだ時と広げた時の上限で止める。
// 広げても流れの中に居る (= 上のメッセージ一覧がその分だけ縮む)。
import { useCallback, useEffect, useLayoutEffect, useState } from 'react'
import { INPUT_FOLDED_LINES, INPUT_OPEN_LINES, lineCap, fitHeight } from './inputSizing.js'

const px = (v) => parseFloat(v) || 0
// line-height が数で決まっていない (= normal) 時に使う、 文字の大きさに対する倍率 (= ブラウザの既定に近い値)
const NORMAL_LINE_HEIGHT = 1.2

// textarea の高さを中身に合わせる。 返り値 = 中身が畳んだ時の上限を超えているか。
function fitTextarea(el, expanded) {
  const cs = getComputedStyle(el)
  const borderY = px(cs.borderTopWidth) + px(cs.borderBottomWidth)
  const metrics = {
    lineHeight: px(cs.lineHeight) || px(cs.fontSize) * NORMAL_LINE_HEIGHT,
    padY: px(cs.paddingTop) + px(cs.paddingBottom),
    borderY,
  }
  // 高さの指定を外して測る (= 外さないと、 前回の指定が「中身の高さ」 として返ってくる)
  el.style.height = ''
  const content = el.scrollHeight + borderY
  const { height } = fitHeight({
    content,
    natural: el.offsetHeight,
    cap: lineCap(metrics, expanded ? INPUT_OPEN_LINES : INPUT_FOLDED_LINES),
  })
  if (height != null) el.style.height = `${height}px`
  return content > lineCap(metrics, INPUT_FOLDED_LINES)
}

export function useInputSizing({ text, textareaRef }) {
  const [expanded, setExpanded] = useState(false)
  const [overflowing, setOverflowing] = useState(false)

  useLayoutEffect(() => {
    const el = textareaRef.current
    if (el) setOverflowing(fitTextarea(el, expanded))
  }, [text, expanded, textareaRef])

  // 幅が変わると折り返しが変わるので、 高さを取り直す (= 回転 / 窓の大きさ / 横の drawer)
  useEffect(() => {
    const el = textareaRef.current
    if (!el || typeof ResizeObserver === 'undefined') return
    let width = el.offsetWidth
    const ro = new ResizeObserver(() => {
      if (el.offsetWidth === width) return
      width = el.offsetWidth
      setOverflowing(fitTextarea(el, expanded))
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [expanded, textareaRef])

  const expand = useCallback(() => setExpanded(true), [])
  const collapse = useCallback(() => setExpanded(false), [])

  return {
    expanded,
    // 開閉のボタンは、 中身が畳んだ時の上限を超えている時だけ意味を持つ
    showToggle: overflowing,
    expand,
    collapse,
  }
}
