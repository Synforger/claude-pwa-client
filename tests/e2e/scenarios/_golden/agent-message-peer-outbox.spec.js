// Golden path: a message for a machine that is down is kept by the sending backend and arrives, once and in order,
// when that machine is back; the tab that wrote it is told.
//
// Two real backends run (= `helpers/run-backend.mjs`, each with its own port and folder) and name each other as the
// other machine. A is the sender's, B the receiver's. B is stopped, two messages are sent to it, B is started again, and
// the watch of A (= every two seconds here, five minutes in production) finds it and sends what was kept.
import { existsSync, readdirSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { test, expect } from '@playwright/test'
import { seedSession } from '../../helpers/fixture.js'
import { PeerBackend } from '../../helpers/peer-backends.js'

const PORT_A = 18865
const PORT_B = 18866
const CHECK_INTERVAL_SEC = 2
const ARRIVAL_TIMEOUT_MS = 90_000

const count = (text, word) => text.split(word).length - 1
const outboxFiles = (backend) => {
  const folder = resolve(backend.dataDir, 'peer_outbox')
  return existsSync(folder) ? readdirSync(folder).filter((name) => name.endsWith('.json')) : []
}
const healthOf = (backend, name) => JSON.parse(readFileSync(resolve(backend.dataDir, 'peer_health.json'), 'utf-8'))[name]

test.describe('golden: agent-message to a machine that is down', () => {
  let a
  let b

  test.beforeAll(async () => {
    a = new PeerBackend({ name: 'a', port: PORT_A, peers: [{ name: 'b', port: PORT_B }], checkIntervalSec: CHECK_INTERVAL_SEC })
    b = new PeerBackend({ name: 'b', port: PORT_B, peers: [{ name: 'a', port: PORT_A }], checkIntervalSec: CHECK_INTERVAL_SEC })
    await Promise.all([a.start(), b.start()])
  })

  test.afterAll(async () => {
    await Promise.all([a?.stop(), b?.stop()])
  })

  test('messages kept while the machine is down arrive once, in order, when it is back', async () => {
    const sender = await seedSession(a.api, 'e2e-tab-a')
    const receiver = await seedSession(b.api, 'e2e-tab-b')
    const to = `b:${receiver.sid}`
    const send = (text) => a.api.post('/agent-messages', { form: { to, from: sender.sid, text } })

    // While B answers, a message goes straight through.
    const direct = await send('first: B is up and takes this at once')
    expect(direct.ok()).toBeTruthy()
    expect((await direct.json()).outbox).toBeUndefined()

    // B stops. The messages sent to it are kept, not refused, and say why.
    await b.stop()
    const kept = []
    for (const text of ['second: kept while B is down', 'third: kept behind the second']) {
      const res = await send(text)
      expect(res.ok()).toBeTruthy()
      const body = await res.json()
      expect(body.outbox).toBe(true)
      expect(body.to).toBe(to)
      expect(body.reason).toBe('peer_unreachable') // 127.0.0.1 is no machine of the tailnet: it cannot be told apart
      expect(body.peer_state.ok).toBe(false)
      kept.push(body)
    }
    expect(outboxFiles(a)).toHaveLength(2)
    expect(healthOf(a, 'b')).toMatchObject({ ok: false, last_error: 'unreachable' })
    expect(readFileSync(receiver.jsonl_path, 'utf-8')).not.toContain('second: kept')

    // B starts again with what it had before. A's watch finds it and sends the kept messages, oldest first.
    await b.start({ reuse: true })
    await expect.poll(() => outboxFiles(a).length, { timeout: ARRIVAL_TIMEOUT_MS, intervals: [1_000] }).toBe(0)
    expect(healthOf(a, 'b')).toMatchObject({ ok: true, last_error: null })

    const record = readFileSync(receiver.jsonl_path, 'utf-8')
    const at = (word) => record.indexOf(word)
    expect([count(record, 'first: B is up'), count(record, 'second: kept'), count(record, 'third: kept')]).toEqual([1, 1, 1])
    expect(at('second: kept')).toBeLessThan(at('third: kept'))

    // The tab that wrote them is told, once for each message.
    const told = readFileSync(sender.jsonl_path, 'utf-8')
    expect(count(told, 'event=\\"delivered\\"')).toBe(2)
    expect(told).toContain(`to=\\"${to}\\"`)

    // The watch looks again and sends nothing a second time.
    await new Promise((done) => setTimeout(done, (CHECK_INTERVAL_SEC + 2) * 1_000))
    const later = readFileSync(receiver.jsonl_path, 'utf-8')
    expect([count(later, 'first: B is up'), count(later, 'second: kept'), count(later, 'third: kept')]).toEqual([1, 1, 1])
  })
})
