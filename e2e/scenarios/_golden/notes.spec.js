// Golden path: notes feature.
// The topbar 📋 button opens the notes of the tab: one markdown file on the host that the
// screen and the tab's agent both write. It renders like a markdown file, never folds, keeps the
// line breaks and spaces of a paragraph as written, is edited in place, and is emptied with Reset.

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
const shown = '[data-testid=notes-text]'
// A heading, then a tree laid out with box-drawing lines, a leading space and spaces that align a
// column, then a path.
const NOTE = '# Tree\n\nroot/\n├─ a/      → one / two\n  └─ dd   → three\n\n~/cpc-e2e-notes/spec.md\n'
const TREE_LINES = ['root/', '├─ a/      → one / two', '  └─ dd   → three']
// The lines of the paragraph as shown (= a line break mark ends a line; spaces read back as spaces).
const shownLines = (page) => page.locator(`${shown} p`).first().evaluate((el) => el.innerText.replace(/\u00a0/g, ' ').split('\n'))

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
    await page.locator('[data-testid=notes-editor]').fill(NOTE)
    await page.locator('[data-testid=notes-save]').click()

    // Rendered like a markdown file: the heading is a heading, the tree keeps its lines and spaces,
    // and the path is something to tap.
    await expect(page.locator(`${shown} h1`)).toHaveText('Tree')
    expect(await shownLines(page)).toEqual(TREE_LINES)
    await expect(page.locator(`${shown} .file-link`)).toHaveText('~/cpc-e2e-notes/spec.md')
    expect(readFileSync(NOTE_FILE, 'utf8')).toBe(NOTE)

    // Still there after closing and reopening, and after a reload.
    await page.locator(`${modal} .modal-close`).click()
    await expect(page.locator(modal)).toHaveCount(0)
    await page.reload({ waitUntil: 'domcontentloaded' })
    await page.locator('[data-testid=chat-input]').waitFor({ state: 'visible' })
    await page.locator('[data-testid=notes-open-button]').click()
    await expect(page.locator(`${shown} h1`)).toHaveText('Tree')

    // Reset asks first, then empties the notes and removes the file.
    await page.locator('[data-testid=notes-reset]').click()
    await page.locator('.confirm-btn.no').click()
    await expect(page.locator(`${shown} h1`)).toHaveText('Tree')
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

  test('long notes are shown whole, never folded', async ({ page, request }) => {
    await seedSession(request, 'e2e-chat-golden')
    mkdirSync(dirname(NOTE_FILE), { recursive: true })
    // Longer than the chat folds a reply (= 4,000 characters), and ending with a heading.
    writeFileSync(NOTE_FILE, `# head\n\n${'a line of the notes\n'.repeat(400)}\n## the last heading\n`)
    await openClient(page, { sid: SID })

    await page.locator('[data-testid=notes-open-button]').click()
    await expect(page.locator(`${shown} h2`)).toHaveText('the last heading')
    await expect(page.locator(`${body} .md-collapse-toggle`)).toHaveCount(0)
    await expect(page.locator(`${body} .md-oversized`)).toHaveCount(0)
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
