// 実行中サブエージェントの description 集合を chat 行へ供給する hook。
//
// 背景 (2026-07-27 audit §1-2): run_in_background の Task は tool_result が
// 「開始 ack」 で即返るため、 chat の Task 行が開始直後から完了の見た目に固まり、
// 実際の完了がどこにも反映されなかった。 真値はサブエージェント panel と同じ
// unified subagents channel (= done 判定は stop_reason OR 親 idle、 backend 側で
// running 固着対策済み) を使い、 行側の 🤖 running-dot をここに連動させる。
//
// 購読は panel と同一 channel の handler 共有 (= refs カウンタ) なので追加接続ゼロ。
// agent が動いていない間はディレクトリ不変で通信も発生しない。
import { useEffect, useState } from 'react'
import { subagentsStreamSse } from '../../transport/select.ts'

const EMPTY = new Set()

export function useRunningSubagents(sid) {
  const [running, setRunning] = useState(EMPTY)
  useEffect(() => {
    setRunning(EMPTY)
    if (!sid) return undefined
    const unsub = subagentsStreamSse.subscribe(sid, (d) => {
      if (!d || typeof d !== 'object') return
      const next = new Set()
      for (const s of d.subagents || []) {
        if (!s.done && s.description) next.add(s.description)
      }
      for (const w of d.workflows || []) {
        if (w.status === 'running' && w.taskId) next.add(w.taskId)
      }
      // 変化が無ければ参照を保つ (= MessageItem memo を無駄に破らない)
      setRunning(prev => {
        if (prev.size === next.size && [...next].every(x => prev.has(x))) return prev
        return next
      })
    })
    return unsub
  }, [sid])
  return running
}
