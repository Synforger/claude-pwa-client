// ADR-012 TransportInspector: SSE/WS 接続の生死 + 直近 100 corr_id を表示。
// transport/* (= ports 経由で得た singleton) の state を読み、 corr_id filter で検索可能。

import { useEffect, useState } from 'react'
import { sseTransport } from '../transport/sse.ts'
import { httpClient } from '../transport/http.ts'

const POLL_INTERVAL_MS = 1_000

export default function TransportInspector() {
  const [tick, setTick] = useState(0)
  const [filter, setFilter] = useState('')
  const recent = httpClient.listRecentCorrIds()

  useEffect(() => {
    const id = setInterval(() => setTick(t => t + 1), POLL_INTERVAL_MS)
    return () => clearInterval(id)
  }, [])

  const filtered = filter
    ? recent.filter(([cid, meta]) => cid.includes(filter) || (meta.path || '').includes(filter))
    : recent

  return (
    <section style={{ padding: 8, fontFamily: 'monospace', fontSize: 12 }}>
      <h3 style={{ margin: '0 0 8px' }}>TransportInspector (tick {tick})</h3>
      <div>SSE state: <strong>{sseTransport.state}</strong></div>
      <div style={{ marginTop: 8 }}>
        <label>filter corr_id / path: </label>
        <input value={filter} onChange={e => setFilter(e.target.value)} style={{ width: 200 }} />
      </div>
      <table style={{ marginTop: 8, borderCollapse: 'collapse', width: '100%' }}>
        <thead>
          <tr>
            <th style={cell}>corr_id</th>
            <th style={cell}>path</th>
            <th style={cell}>status</th>
            <th style={cell}>ts</th>
          </tr>
        </thead>
        <tbody>
          {filtered.slice(0, 100).map(([cid, meta]) => (
            <tr key={cid}>
              <td style={cell}>{cid}</td>
              <td style={cell}>{meta.path}</td>
              <td style={cell}>{meta.status}</td>
              <td style={cell}>{new Date(meta.ts).toISOString().slice(11, 23)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  )
}

const cell = { border: '1px solid #ddd', padding: '2px 6px', textAlign: 'left' }
