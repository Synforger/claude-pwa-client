// Golden path: an API tab (no Claude Code behind it) is a conversation that is only shown.
//
// A backend of its own runs with one API tab declared (`run-backend.mjs`, CPC_E2E_API_TABS=1): its record already holds
// a question and an answer that carries a `usage`, and its wallet this month's spend. The screen shows the conversation
// and the context amount (in the list and in the top bar), offers no input, terminal, stop or menu, and follows a row the
// program appends to the record.
import { appendFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { test, expect } from '@playwright/test'
import { PeerBackend } from '../../helpers/peer-backends.js'

const PORT = 18870
const API_SID = 'api_support-bot'

test.describe('golden: api-tab', () => {
  test.setTimeout(120_000)
  let backend

  test.beforeAll(async () => {
    backend = new PeerBackend({ name: 'api-tab', port: PORT, extraEnv: { CPC_E2E_API_TABS: '1' } })
    await backend.start()
  })

  test.afterAll(async () => {
    await backend?.stop()
  })

  test('shows the conversation and the context amount, offers nothing that needs a Claude Code, and follows the record', async ({ page }) => {
    await page.goto(`${backend.baseURL}/?ses=${API_SID}`, { waitUntil: 'domcontentloaded' })

    // The conversation is drawn as any other: the question and the answer of the record.
    await expect(page.getByText('How long is the return window?')).toBeVisible({ timeout: 20_000 })
    await expect(page.getByText('Thirty days from delivery.')).toBeVisible()

    // Where the input would be, one line says it is only shown; nothing that needs a Claude Code is offered.
    await expect(page.locator('[data-testid=api-tab-readonly]')).toBeVisible()
    await expect(page.locator('[data-testid=chat-input]')).toHaveCount(0)
    await expect(page.locator('[data-testid=more-menu-toggle]')).toHaveCount(0)
    await expect(page.locator('[data-testid=notes-open-button]')).toHaveCount(0)

    // The top bar shows the context amount (300 + 12,000 + 0 tokens) and the wallet's spend this month, and no 5h / 7d.
    await expect(page.locator('[data-testid=status-bar-api-context]')).toContainText('12.3k')
    await expect(page.locator('[data-testid=status-bar-api-spend]')).toContainText('123 / 1,000 JPY')
    await expect(page.locator('[data-testid=status-bar]')).not.toContainText(/NaN|5h|7d/)

    // The list row shows the name and the amount, with no mark of work, sleep, account or unread and no menu.
    await page.locator('[data-testid=drawer-toggle]').click()
    const row = page.locator(`[data-cpc-sid=${API_SID}]`)
    await expect(row.locator('.drawer-item-title')).toHaveText('Support bot')
    await expect(row.locator('[data-testid=session-context]')).toHaveText('12.3k')
    await expect(row.locator('.tab-badge, [data-testid=session-asleep], .drawer-item-account, .drawer-item-menu')).toHaveCount(0)

    // A row the program appends reaches the open screen within seconds: the answer, and the new context amount.
    const record = resolve(backend.runtimeDir, 'api', 'support-bot.jsonl')
    const at = new Date().toISOString()
    appendFileSync(record, JSON.stringify({ type: 'user', uuid: 'api-u2', timestamp: at,
      message: { role: 'user', content: 'And for opened items?' } }) + '\n')
    appendFileSync(record, JSON.stringify({ type: 'assistant', uuid: 'api-a2', timestamp: at, message: {
      id: 'msg_api_a2', role: 'assistant', model: 'claude-sonnet-5-5', stop_reason: 'end_turn',
      content: [{ type: 'text', text: 'Fourteen days if unused.' }],
      usage: { input_tokens: 400, cache_read_input_tokens: 45000, cache_creation_input_tokens: 200, output_tokens: 7 } } }) + '\n')
    await expect(page.getByText('Fourteen days if unused.')).toBeVisible({ timeout: 10_000 })
    await expect(page.locator('[data-testid=status-bar-api-context]')).toContainText('45.6k', { timeout: 10_000 })
    await expect(row.locator('[data-testid=session-context]')).toHaveText('45.6k', { timeout: 10_000 })
  })
})
