// 一番上の帯 (= StatusBar) を包む要素の高さを測り、 CSS 変数 --app-bar-h として host に渡す。
// 左に置いたままのタブの一覧が、 帯の下から始まるために使う (= 帯の高さは文字の大きさや折り返しで変わるので決め打ちしない)。
// React の state には入れない: 帯の大きさが変わるたびに Layout 全体を描き直さないため、 style へ直に書く。

import { useLayoutEffect } from 'react'

export const APP_BAR_HEIGHT_VAR = '--app-bar-h'

export function useAppBarHeight(hostRef, barRef) {
  useLayoutEffect(() => {
    const host = hostRef.current
    const bar = barRef.current
    if (!host || !bar) return undefined
    const apply = () => host.style.setProperty(APP_BAR_HEIGHT_VAR, `${bar.getBoundingClientRect().height}px`)
    apply()
    if (typeof ResizeObserver === 'undefined') return undefined
    const observer = new ResizeObserver(apply)
    observer.observe(bar)
    return () => observer.disconnect()
  }, [hostRef, barRef])
}
