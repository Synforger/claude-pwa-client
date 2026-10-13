// Golden path: notes feature.
// The topbar 📋 button opens the notes of the tab: one markdown file on the host that the
// screen and the tab's agent both write. It renders like the chat, is edited in place, and
// is emptied with Reset.

import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { test, expect } from '@playwright/test'
import { seedSession, appendEvent } from '../../helpers/fixture.js'
import { openClient } from '../../helpers/pwa.js'

const SID = 'ses_e2echatgld'
// Where the test backend keeps this tab's notes (= what the agent gets as PWA_NOTE).
const NOTE_FILE = resolve(
  dirname(fileURLToPath(import.meta.url)), '..', '..', 'fixtures', '_runtime', 'user', 'notes', `${SID}.md`,
)
const modal = '[data-testid=notes-modal]'
const body = '[data-testid=notes-body]'

// One step of the agent's own: a tool call and its result (= what moves `current_tool`).
function toolStep(jsonlPath, id) {
  const at = Date.now()
  appendEvent(jsonlPath, {
    type: 'assistant', uuid: `a-${id}`, timestamp: new Date(at).toISOString(),
    message: { id: `msg_${id}`, role: 'assistant', stop_reason: 'tool_use',
      content: [{ type: 'tool_use', id: `tool_${id}`, name: 'Write', input: { file_path: NOTE_FILE, content: '' } }] },
  })
  appendEvent(jsonlPath, {
    type: 'user', uuid: `r-${id}`, timestamp: new Date(at + 50).toISOString(),
    message: { role: 'user', content: [{ type: 'tool_result', tool_use_id: `tool_${id}`, content: 'ok' }] },
  })
}

test.describe('golden: notes', () => {
  test.beforeEach(() => { rmSync(NOTE_FILE, { force: true }) })
  test.afterEach(() => { rmSync(NOTE_FILE, { force: true }) })

  test('the 📋 button opens the notes; they are written in place, kept on the host, and emptied with Reset', async ({ page, request }) => {
    await seedSession(request, 'e2e-chat-golden')
    await openClient(page, { sid: SID })

    await page.locator('[data-testid=notes-open-button]').click()
    await expect(page.locator(modal)).toBeVisible({ timeout: 5_000 })
    // Nothing written yet: the screen says so, there is nothing to reset, and no file exists.
    await expect(page.locator(`${body} .note-empty`)).toBeVisible()
    await expect(page.locator('[data-testid=notes-reset]')).toHaveCount(0)
    expect(existsSync(NOTE_FILE)).toBe(false)

    await page.locator('[data-testid=notes-edit]').click()
    await page.locator('[data-testid=notes-editor]').fill('# Input design\n\n- stops at six lines\n\n~/cpc-e2e-notes/spec.md\n')
    await page.locator('[data-testid=notes-save]').click()

    // Rendered like the chat: a heading, a list, and the path as something to tap.
    await expect(page.locator(`${body} h1`)).toHaveText('Input design')
    await expect(page.locator(`${body} li`)).toHaveText('stops at six lines')
    await expect(page.locator(`${body} .file-link`)).toContainText('~/cpc-e2e-notes/spec.md')
    expect(readFileSync(NOTE_FILE, 'utf8')).toBe('# Input design\n\n- stops at six lines\n\n~/cpc-e2e-notes/spec.md\n')

    // Still there after closing and reopening, and after a reload.
    await page.locator(`${modal} .modal-close`).click()
    await expect(page.locator(modal)).toHaveCount(0)
    await page.reload({ waitUntil: 'domcontentloaded' })
    await page.locator('[data-testid=chat-input]').waitFor({ state: 'visible' })
    await page.locator('[data-testid=notes-open-button]').click()
    await expect(page.locator(`${body} h1`)).toHaveText('Input design')

    // Reset asks first, then empties the notes and removes the file.
    await page.locator('[data-testid=notes-reset]').click()
    await page.locator('.confirm-btn.no').click()
    await expect(page.locator(`${body} h1`)).toHaveText('Input design')
    await page.locator('[data-testid=notes-reset]').click()
    await page.locator('.confirm-btn.yes').click()
    await expect(page.locator(`${body} .note-empty`)).toBeVisible()
    await expect.poll(() => existsSync(NOTE_FILE)).toBe(false)
  })

  test('what the agent writes to the file shows up, also while the notes stay open', async ({ page, request }) => {
    const seeded = await seedSession(request, 'e2e-chat-golden')
    mkdirSync(dirname(NOTE_FILE), { recursive: true })
    writeFileSync(NOTE_FILE, 'first draft by the agent\n')
    await openClient(page, { sid: SID })

    await page.locator('[data-testid=notes-open-button]').click()
    await expect(page.locator(body)).toContainText('first draft by the agent')

    // The agent rewrites the file with a tool while the notes are open.
    writeFileSync(NOTE_FILE, 'second draft by the agent\n')
    toolStep(seeded.jsonl_path, `note-${Date.now()}`)
    await expect(page.locator(body)).toContainText('second draft by the agent', { timeout: 10_000 })
  })

  test('a path in the notes opens in the preview', async ({ page, request }) => {
    await seedSession(request, 'e2e-chat-golden')
    mkdirSync(dirname(NOTE_FILE), { recursive: true })
    writeFileSync(NOTE_FILE, 'see ~/cpc-e2e-notes/spec.md\n')
    await openClient(page, { sid: SID })

    await page.locator('[data-testid=notes-open-button]').click()
    await page.locator(`${body} .file-link`).click()
    await expect(page.locator('[data-testid=file-preview-modal]')).toBeVisible({ timeout: 10_000 })
    await expect(page.locator('[data-testid=file-preview-path]')).toContainText('cpc-e2e-notes/spec.md')
    await expect(page.locator(modal)).toHaveCount(0)
  })
})
