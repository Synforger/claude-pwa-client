// ADR-012 StateInspector: /debug/state を 2 秒間隔で叩いて backend in-memory state の live tree を表示。
// frontend 局所 state (= state/* module) は W2 着地後に state hook を import して表示する設計。

import { useEffect, useState } from 'react'
import { httpClient } from '../transport/http.ts'

const POLL_INTERVAL_MS = 2_000

export default function StateInspector() {
  const [snapshot, setSnapshot] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    let cancelled = false
    let timer = null

    async function tick() {
      try {
        const res = await httpClient.apiFetch('/debug/state', { timeout: 3_000 })
        if (cancelled) return
        if (!res.ok) {
          setError(`/debug/state ${res.status}`)
          return
        }
        const body = await res.json()
        if (cancelled) return
        setSnapshot(body)
        setError(null)
      } catch (e) {
        if (cancelled) return
        setError(String(e?.message || e))
      } finally {
        if (!cancelled) timer = setTimeout(tick, POLL_INTERVAL_MS)
      }
    }
    tick()
    return () => {
      cancelled = true
      if (timer !== null) clearTimeout(timer)
    }
  }, [])

  return (
    <section style={{ padding: 8, fontFamily: 'monospace', fontSize: 12 }}>
      <h3 style={{ margin: '0 0 8px' }}>StateInspector</h3>
      {error ? <div style={{ color: 'red' }}>error: {error}</div> : null}
      {snapshot ? (
        <pre style={{ margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
          {JSON.stringify(snapshot, null, 2)}
        </pre>
      ) : (
        <div>loading…</div>
      )}
    </section>
  )
}
