// Contract: ADR-013 heartbeat - the PTY WS replies pong to a client ping so
// the dead-but-OPEN detection in transport/ws-pty.js can force a reconnect
// once 60s pass without a reply.

import { test, expect } from '@playwright/test'
import { WebSocket } from 'ws'

const SID = 'ses_e2eheartbt'
const BASE = process.env.CPC_E2E_BASE_URL || 'http://127.0.0.1:18765'

test.describe('contract: heartbeat dead-but-OPEN', () => {
  test('PTY WS replies pong to a client ping', async ({ request }) => {
    await request.post('/debug/e2e/seed', { data: {
      sid: SID,
      agent_id: 'agent_e2e',
      account_id: 'e2e',
      jsonl_events: [],
    } })

    const wsUrl = BASE.replace(/^http/, 'ws') + `/ws/pty/${encodeURIComponent(SID)}`
    const ws = new WebSocket(wsUrl)
    try {
      await new Promise((resolve, reject) => {
        ws.on('open', resolve)
        ws.on('error', reject)
      })
      const pong = await new Promise((resolve, reject) => {
        const timer = setTimeout(() => reject(new Error('pong timeout')), 5_000)
        ws.on('message', (data, isBinary) => {
          if (isBinary) return
          try {
            const msg = JSON.parse(data.toString())
            if (msg.type === 'pong') { clearTimeout(timer); resolve(msg) }
          } catch { /* not a control frame; ignore */ }
        })
        ws.send(JSON.stringify({ type: 'ping', ts: Date.now() }))
      })
      expect(pong).toMatchObject({ type: 'pong' })
    } finally {
      ws.close()
    }
  })
})
