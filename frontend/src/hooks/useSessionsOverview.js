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
 * 送信直後の楽観 window (pendingSendUntilRef) 中だけは busy=false の上書きをスキップする
 * (= 最初の SSE event 到達まで楽観 loading を維持して停止ボタンをチラつかせない)。
 *
 * 停止ボタン経路は backend に /sessions/{sid}/stop で意思を送り、 backend が
 * StreamState.user_stopped を立てて busy=false を強制 + 全 client に push するので、
 * frontend 側で別フラグを持つ必要は無い (= backend 権威に一本化)。
 */
import { useEffect } from 'react'
import { apiUrl } from '../utils/api.js'

export function useSessionsOverview({ setLoading, pendingSendUntilRef }) {
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
  }, [setLoading, pendingSendUntilRef])
}
