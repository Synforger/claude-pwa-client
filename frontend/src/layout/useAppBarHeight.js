// Measures the element that wraps the bar at the top (StatusBar) and gives its height to the host as the CSS variable --app-bar-h.
// The docked tab list starts below it; the height is measured, not fixed, because text size and wrapping change it.
// It is written straight to the style, not into React state, so a change of the bar's size does not redraw all of Layout.

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
