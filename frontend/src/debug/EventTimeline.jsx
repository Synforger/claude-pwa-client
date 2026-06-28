// ADR-012 EventTimeline: backend /debug/log を 3 秒間隔で叩いて event_journal を時系列表示。
// seq の連続性 (= 抜けがないか) + 同 sid 内 ts の単調性をチェックして「重複 / order ズレ」 を視覚化。

import { useEffect, useState } from 'react'
import { httpClient } from '../transport/http.ts'

const POLL_INTERVAL_MS = 3_000
const LIMIT = 200

export default function EventTimeline() {
  const [entries, setEntries] = useState([])
  const [error, setError] = useState(null)
  const [sidFilter, setSidFilter] = useState('')

  useEffect(() => {
    let cancelled = false
    let timer = null

    async function tick() {
      try {
        const q = sidFilter ? `?limit=${LIMIT}&sid=${encodeURIComponent(sidFilter)}` : `?limit=${LIMIT}`
        const res = await httpClient.apiFetch(`/debug/log${q}`, { timeout: 5_000 })
        if (cancelled) return
        if (!res.ok) {
          setError(`/debug/log ${res.status}`)
        } else {
          const body = await res.json()
          if (cancelled) return
          setEntries(body.entries || [])
          setError(null)
        }
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
  }, [sidFilter])

  // seq 連続性 / ts 単調性チェック
  const anomalies = []
  for (let i = 1; i < entries.length; i++) {
    const prev = entries[i - 1]
    const cur = entries[i]
    if (cur.seq !== prev.seq + 1) {
      anomalies.push(`seq gap ${prev.seq} → ${cur.seq} at idx ${i}`)
    }
    if (prev.sid === cur.sid && typeof prev.ts === 'number' && typeof cur.ts === 'number' && cur.ts < prev.ts) {
      anomalies.push(`ts backstep on sid ${cur.sid} at seq ${cur.seq}`)
    }
  }

  return (
    <section style={{ padding: 8, fontFamily: 'monospace', fontSize: 12 }}>
      <h3 style={{ margin: '0 0 8px' }}>EventTimeline</h3>
      <div>
        sid filter: <input value={sidFilter} onChange={e => setSidFilter(e.target.value)} style={{ width: 200 }} />
      </div>
      {error ? <div style={{ color: 'red' }}>error: {error}</div> : null}
      {anomalies.length > 0 ? (
        <ul style={{ color: 'orange', marginTop: 8 }}>
          {anomalies.slice(0, 10).map((a, i) => <li key={i}>{a}</li>)}
        </ul>
      ) : null}
      <table style={{ marginTop: 8, borderCollapse: 'collapse', width: '100%' }}>
        <thead>
          <tr>
            <th style={cell}>seq</th>
            <th style={cell}>ts</th>
            <th style={cell}>sid</th>
            <th style={cell}>kind</th>
            <th style={cell}>event (truncated)</th>
          </tr>
        </thead>
        <tbody>
          {entries.slice().reverse().slice(0, 100).map(e => (
            <tr key={e.seq}>
              <td style={cell}>{e.seq}</td>
              <td style={cell}>{typeof e.ts === 'number' ? new Date(e.ts * 1000).toISOString().slice(11, 23) : '-'}</td>
              <td style={cell}>{e.sid}</td>
              <td style={cell}>{e.kind}</td>
              <td style={cell}>{JSON.stringify(e.event).slice(0, 200)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  )
}

const cell = { border: '1px solid #ddd', padding: '2px 6px', textAlign: 'left' }
