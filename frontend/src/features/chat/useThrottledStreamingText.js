import { useEffect, useRef, useState } from 'react'

// streaming 中の markdown 再パース間引き (= 2026-07-10 発熱対策)。
//
// 背景: streaming bubble は SSE event ごと (= 秒 5〜20 回) に text が伸び、 そのたびに
// ReactMarkdown が**全文**を再パース + ハイライトする。 応答が長いほど 1 回のパースが
// 重くなる × 高頻度 = iPhone の main thread が回りっぱなし (= バッテリー 93% 消費の
// 主容疑)。 useDeferredValue は優先度を下げるだけで回数は減らさない。
//
// この hook は streaming 中の値更新を THROTTLE_MS に 1 回へ間引く (= leading +
// trailing: 最初は即時反映、 以降は間隔内の更新を 1 回に畳む)。 streaming が
// 終わった瞬間は間引かず最終 text を同期で返す (= 完成形の表示が遅れない)。
export const STREAMING_RENDER_THROTTLE_MS = 500

export function useThrottledStreamingText(text, streaming, ms = STREAMING_RENDER_THROTTLE_MS) {
  const [value, setValue] = useState(text)
  const lastAppliedAtRef = useRef(0)
  const timerRef = useRef(null)

  useEffect(() => {
    if (!streaming) {
      // 完了 (or 非 streaming bubble): timer を破棄して最終 text に即追従。
      if (timerRef.current) {
        clearTimeout(timerRef.current)
        timerRef.current = null
      }
      setValue(text)
      lastAppliedAtRef.current = Date.now()
      return undefined
    }
    const elapsed = Date.now() - lastAppliedAtRef.current
    if (elapsed >= ms) {
      lastAppliedAtRef.current = Date.now()
      setValue(text)
      return undefined
    }
    // 間隔内: trailing 更新を 1 本だけ予約 (= 最新 text で上書き予約、 古い予約は破棄)。
    if (timerRef.current) clearTimeout(timerRef.current)
    timerRef.current = setTimeout(() => {
      timerRef.current = null
      lastAppliedAtRef.current = Date.now()
      setValue(text)
    }, ms - elapsed)
    return undefined
  }, [text, streaming, ms])

  // unmount 時の timer 掃除。
  useEffect(() => () => { if (timerRef.current) clearTimeout(timerRef.current) }, [])

  // 非 streaming は常に素の text (= state の 1 frame 遅れも作らない)。
  return streaming ? value : text
}
