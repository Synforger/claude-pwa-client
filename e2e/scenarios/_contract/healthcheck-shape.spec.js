// Contract: /debug/healthcheck must keep its shape so the operator script
// (scripts/healthcheck.sh) and any future automation can rely on the field
// layout. Adding new checks is fine; renaming or removing one is not.
//
// Coverage:
//   - Endpoint is reachable on loopback with the configured Host header.
//   - Top-level shape: ts, pid, summary{total,pass,fail}, checks{...}.
//   - Every check returns at minimum { ok: <bool> }.
//   - The 12 canonical check names are present (= the operator-facing
//     contract the scripts/healthcheck.sh exit code logic depends on).
//   - DNS rebinding defence still applies: a foreign Host returns 403.

import { test, expect } from '@playwright/test'

const EXPECTED_CHECKS = [
  'liveness',
  'config',
  'agent_launch_alias',
  'session_meta',
  'jsonl_bindings',
  'claude_jsonl_files',
  'files_tree',
  'tmux_pty_sessions',
  'vapid',
  'subscriptions',
  'push_dry_run',
  'backend_error_log',
]

test.describe('contract: /debug/healthcheck shape', () => {
  test('returns the documented JSON layout', async ({ request }) => {
    const res = await request.get('/debug/healthcheck')
    expect(res.status()).toBe(200)
    const body = await res.json()

    expect(typeof body.ts).toBe('number')
    expect(typeof body.pid).toBe('number')

    expect(body.summary).toBeTruthy()
    expect(typeof body.summary.total).toBe('number')
    expect(typeof body.summary.pass).toBe('number')
    expect(typeof body.summary.fail).toBe('number')
    expect(body.summary.total).toBe(body.summary.pass + body.summary.fail)

    expect(body.checks).toBeTruthy()
    for (const name of EXPECTED_CHECKS) {
      expect(body.checks[name], `missing check: ${name}`).toBeTruthy()
      expect(typeof body.checks[name].ok).toBe('boolean')
    }
    expect(body.summary.total).toBe(EXPECTED_CHECKS.length)
  })

  test('rejects a foreign Host header (= DNS rebinding defence)', async ({ request }) => {
    const res = await request.get('/debug/healthcheck', {
      headers: { host: 'attacker.example.com' },
    })
    expect(res.status()).toBe(403)
  })
})
