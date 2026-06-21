/**
 * クリック・タップが ref 要素の外側で発生したら onOutside を呼ぶ hook (= F-29 集約)。
 *
 * 5 component (= SessionDrawer / SubagentsModal / StatusBar 等) で手書き重複していた
 *   useEffect(() => {
 *     const handler = (e) => { if (ref.current && !ref.current.contains(e.target)) onClose() }
 *     document.addEventListener('mousedown', handler)
 *     return () => document.removeEventListener('mousedown', handler)
 *   }, [...])
 * を 1 か所に集約。
 *
 * options:
 *   - enabled: false で no-op (= modal が閉じてる間 listener を張らない、 既定 true)
 *   - eventName: 'mousedown' (= 既定。 touchstart を含めたいなら呼出側で第二 hook 呼び)
 *   - ignore: (target: Element) => boolean (= true を返した要素は外側扱いしない、
 *     例えば「開閉トリガ button」 が outside 扱いされて即閉じるのを防ぐ)
 *
 * onOutside は最新参照を ref で持つ (= 再 render で再 listener 張替えない)。
 */
import { useEffect, useRef } from 'react'

export function useOutsideClick(elementRef, onOutside, options = {}) {
  const { enabled = true, eventName = 'mousedown', ignore } = options
  const onOutsideRef = useRef(onOutside)
  const ignoreRef = useRef(ignore)
  useEffect(() => { onOutsideRef.current = onOutside }, [onOutside])
  useEffect(() => { ignoreRef.current = ignore }, [ignore])

  useEffect(() => {
    if (!enabled) return undefined
    const handler = (e) => {
      const el = elementRef?.current
      if (!el) return
      const target = e.target
      if (!target || !(target instanceof Node)) return
      if (el.contains(target)) return
      const ig = ignoreRef.current
      if (typeof ig === 'function') {
        try { if (ig(target)) return } catch { /* ignore */ }
      }
      try { onOutsideRef.current?.(e) } catch { /* ignore */ }
    }
    document.addEventListener(eventName, handler)
    return () => document.removeEventListener(eventName, handler)
  }, [elementRef, enabled, eventName])
}
