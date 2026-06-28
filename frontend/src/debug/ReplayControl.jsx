// ADR-012 ReplayControl: backend /debug/replay を叩いて event_journal を SSE で再生。
// EventSource 直接接続でなく fetch POST + body 設定が必要なので、 transport の apiFetch + ReadableStream で読む。

import { useRef, useState } from 'react'
import { httpClient } from '../transport/http.ts'

export default function ReplayControl() {
  const [sid, setSid] = useState('')
  const [startTs, setStartTs] = useState('')
  const [endTs, setEndTs] = useState('')
  const [speed, setSpeed] = useState('1.0')
  const [running, setRunning] = useState(false)
  const [frames, setFrames] = useState([])
  const abortRef = useRef(null)

  async function start() {
    if (running) return
    const ctrl = new AbortController()
    abortRef.current = ctrl
    setRunning(true)
    setFrames([])
    try {
      const res = await httpClient.apiFetch('/debug/replay', {
        method: 'POST',
        jsonBody: {
          sid: sid || null,
          start_ts: startTs ? Number(startTs) : null,
          end_ts: endTs ? Number(endTs) : null,
          speed: Number(speed) || 0,
        },
        timeout: 0,  // SSE は長期接続、 timeout なし
        signal: ctrl.signal,
      })
      if (!res.body) throw new Error('no response body')
      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buf = ''
      while (true) {
        const { value, done } = await reader.read()
        if (done) break
        buf += decoder.decode(value, { stream: true })
        let idx
        while ((idx = buf.indexOf('\n\n')) >= 0) {
          const raw = buf.slice(0, idx)
          buf = buf.slice(idx + 2)
          const dataLine = raw.split('\n').find(l => l.startsWith('data:'))
          if (!dataLine) continue
          try {
            const payload = JSON.parse(dataLine.slice(5).trim())
            setFrames(prev => [...prev.slice(-99), payload])
          } catch (e) {
            console.warn('[replay] parse failed', e)
          }
        }
      }
    } catch (e) {
      if (e?.name !== 'AbortError') console.warn('[replay] aborted/failed', e)
    } finally {
      setRunning(false)
      abortRef.current = null
    }
  }

  function stop() {
    abortRef.current?.abort()
  }

  return (
    <section style={{ padding: 8, fontFamily: 'monospace', fontSize: 12 }}>
      <h3 style={{ margin: '0 0 8px' }}>ReplayControl</h3>
      <div style={{ display: 'grid', gridTemplateColumns: 'auto 1fr', gap: 4, maxWidth: 400 }}>
        <label>sid</label><input value={sid} onChange={e => setSid(e.target.value)} />
        <label>start_ts</label><input value={startTs} onChange={e => setStartTs(e.target.value)} placeholder="epoch sec" />
        <label>end_ts</label><input value={endTs} onChange={e => setEndTs(e.target.value)} placeholder="epoch sec" />
        <label>speed</label><input value={speed} onChange={e => setSpeed(e.target.value)} placeholder="0=即流し / 1=実時間" />
      </div>
      <div style={{ marginTop: 8 }}>
        <button onClick={start} disabled={running}>start</button>
        <button onClick={stop} disabled={!running} style={{ marginLeft: 8 }}>stop</button>
        <span style={{ marginLeft: 8 }}>{running ? 'streaming…' : 'idle'} · {frames.length} frames</span>
      </div>
      <ul style={{ marginTop: 8, maxHeight: 240, overflow: 'auto', padding: 0, listStyle: 'none' }}>
        {frames.slice().reverse().map((f, i) => (
          <li key={i} style={{ borderBottom: '1px solid #eee', padding: '2px 0' }}>
            sid={f.sid} kind={f.kind} ts={f.replay_ts}
            <pre style={{ margin: 0, fontSize: 11 }}>{JSON.stringify(f.event)}</pre>
          </li>
        ))}
      </ul>
    </section>
  )
}
