/**
 * 全 session の busy 状態を 1 本の SSE (/sessions/overview/stream) で購読し、
 * loading[sid] を backend 権威の busy で上書きする (= 案B)。
 *
 * 旧来 loading は active タブの chat SSE (assistant/result) だけで駆動していたため、
 * 非アクティブタブは SSE 非接続で turn 完了を追えず青丸が stuck していた。 本 hook は
 * backend が全 session の JSONL から算出した busy を 1 接続で受けるので:
 *   - 非アクティブタブの青丸/赤丸が live 追従する
 *   - active タブの result 取りこぼし (= loading が落ちない) も backend busy が補正する
 *
 * 楽観 window 中は backend busy の上書きを方向別にスキップする:
 *   - pendingSendUntilRef (送信直後): busy=false で上書きしない (= loading を維持)
 *   - stopUntilRef (停止直後): busy=true で上書きしない (= 停止ボタンが復活しないように)
 *     claude が Esc を受けて result 行を書くまで backend は busy=true のまま流すので、
 *     ここで止めないと「停止押す → 一瞬消える → 即復活」 のチラつきになる。
 */
import { useEffect } from 'react'
import { apiUrl } from '../utils/api.js'

export function useSessionsOverview({ setLoading, pendingSendUntilRef, stopUntilRef }) {
  useEffect(() => {
    const es = new EventSource(apiUrl('/sessions/overview/stream'))
    es.onmessage = (e) => {
      if (!e.data) return
      let payload
      try {
        payload = JSON.parse(e.data)
      } catch {
        return
      }
      setLoading(prev => {
        const next = { ...prev }
        let changed = false
        const now = Date.now()
        for (const sid of Object.keys(payload)) {
          const busy = !!payload[sid]?.busy
          if (!busy && (pendingSendUntilRef?.current?.[sid] || 0) > now) continue
          if (busy && (stopUntilRef?.current?.[sid] || 0) > now) continue
          if (!!next[sid] !== busy) {
            next[sid] = busy
            changed = true
          }
        }
        return changed ? next : prev
      })
    }
    es.onerror = () => { /* EventSource は自動再接続 (= 一時切断は無視) */ }
    return () => es.close()
  }, [setLoading, pendingSendUntilRef, stopUntilRef])
}
