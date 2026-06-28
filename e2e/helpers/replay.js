// Thin client over POST /debug/replay. Pushes a scripted event sequence into
// the live SSE stream so scenarios can deterministically reproduce a server
// race / ordering bug without touching the watcher.
import { readFileSync } from 'node:fs'

export async function pushReplay(request, scenarioPath, { sid, speed = 0 } = {}) {
  const raw = readFileSync(scenarioPath, 'utf-8')
  const body = JSON.parse(raw)
  const payload = { sid, speed, ...body }
  const res = await request.post('/debug/replay', { data: payload })
  if (!res.ok()) {
    throw new Error(`/debug/replay failed: ${res.status()} ${await res.text()}`)
  }
  return res.json()
}
