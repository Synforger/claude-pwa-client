/**
 * Escape key 検知の集約 hook (= F-29)。
 *
 * 既存の modal / drawer 等で `keydown` listener を手書きで張って Escape を判定する
 * パターンが複数あったので 1 か所に統合。
 *
 * options:
 *   - enabled: false で listener を張らない (= 既定 true)
 *   - target: window | document (= 既定 window)
 *
 * onEscape は最新参照を ref で持つ。
 */
import { useEffect, useRef } from 'react'

export function useEscape(onEscape, options = {}) {
  const { enabled = true, target } = options
  const onEscapeRef = useRef(onEscape)
  useEffect(() => { onEscapeRef.current = onEscape }, [onEscape])

  useEffect(() => {
    if (!enabled) return undefined
    const t = target || (typeof window !== 'undefined' ? window : null)
    if (!t || typeof t.addEventListener !== 'function') return undefined
    const handler = (e) => {
      if (e.key !== 'Escape' && e.key !== 'Esc') return
      try { onEscapeRef.current?.(e) } catch { /* ignore */ }
    }
    t.addEventListener('keydown', handler)
    return () => t.removeEventListener('keydown', handler)
  }, [enabled, target])
}
