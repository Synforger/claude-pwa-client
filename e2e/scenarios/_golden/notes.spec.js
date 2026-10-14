// Golden path: notes feature.
// The topbar 📋 button opens the notes of the tab: one markdown file on the host that the
// screen and the tab's agent both write. It renders like a markdown file, never folds, keeps the
// line breaks and spaces of a paragraph as written, is edited in place, and is emptied with Reset.

import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { homedir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { test, expect } from '@playwright/test'
import { seedSession, appendEvent } from '../../helpers/fixture.js'
import { openClient } from '../../helpers/pwa.js'
// The size limits are constants in the frontend; read from there so changing them means no edit here.
import { TEXT_ZOOM_MAX, TEXT_ZOOM_MIN } from '../../../frontend/src/hooks/textZoom.js'

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

// A code block and a table wider than any phone, and a path to a markdown file with the same.
const WIDE_LINE = Array.from({ length: 24 }, (_, i) => `column${i}`).join(' ')
const WIDE_TABLE = `| ${Array.from({ length: 10 }, (_, i) => `heading_number_${i}`).join(' | ')} |\n`
  + `|${' --- |'.repeat(10)}\n| ${Array.from({ length: 10 }, (_, i) => `cell_with_long_text_${i}`).join(' | ')} |\n`
const WIDE_MD = `# wide\n\n\`\`\`\n${WIDE_LINE}\n\`\`\`\n\n${WIDE_TABLE}`
// /file/raw only serves files under HOME (= see file-preview.spec.js).
const WIDE_FILE = join(homedir(), '.cache', 'cpc-e2e', 'notes-wide.md')

// How far the shown markdown reaches past its frame sideways (= 0 when it never moves sideways),
// and the size it is drawn at.
const sideways = (frame) => frame.evaluate((el) => el.scrollWidth - el.clientWidth)
const zoomOf = (content) => content.evaluate((el) => Number(el.style.zoom || 1))

// Fingers and the wheel are sent as events made inside the page: the browsers under test have no
// multi-touch input of their own. A touch carries only what the screen reads (= where each finger is).
function pinch(frame, from, to) {
  return frame.evaluate((el, { from, to }) => {
    const r = el.getBoundingClientRect()
    const cx = r.left + r.width / 2
    const cy = r.top + r.height / 2
    const fingers = (spread) => [{ clientX: cx - spread / 2, clientY: cy }, { clientX: cx + spread / 2, clientY: cy }]
    const send = (type, touches) => {
      const event = new Event(type, { bubbles: true, cancelable: true })
      Object.defineProperty(event, 'touches', { value: touches })
      el.dispatchEvent(event)
    }
    send('touchstart', fingers(from))
    for (let k = 1; k <= 5; k += 1) send('touchmove', fingers(from + (to - from) * k / 5))
    send('touchend', [])
  }, { from, to })
}
function ctrlWheel(frame, deltaY) {
  return frame.evaluate((el, deltaY) => {
    const r = el.getBoundingClientRect()
    el.dispatchEvent(new WheelEvent('wheel', {
      bubbles: true, cancelable: true, ctrlKey: true, deltaY, deltaMode: 0,
      clientX: r.left + r.width / 2, clientY: r.top + r.height / 2,
    }))
  }, deltaY)
}

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
  test.afterEach(() => { rmSync(NOTE_FILE, { force: true }); rmSync(WIDE_FILE, { force: true }) })

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

  // Nothing moves sideways: a wide code block and a wide table fold into the width, in the notes
  // and in a markdown file opened from them.
  test('wide code blocks and tables fold into the width, in the notes and in a markdown preview', async ({ page, request }) => {
    await seedSession(request, 'e2e-chat-golden')
    mkdirSync(dirname(NOTE_FILE), { recursive: true })
    mkdirSync(dirname(WIDE_FILE), { recursive: true })
    writeFileSync(NOTE_FILE, `${WIDE_MD}\n${WIDE_FILE}\n`)
    writeFileSync(WIDE_FILE, WIDE_MD)
    await openClient(page, { sid: SID })

    await page.locator('[data-testid=notes-open-button]').click()
    await expect(page.locator(`${shown} table`)).toBeVisible()
    expect(await sideways(page.locator(body))).toBeLessThanOrEqual(0)
    expect(await sideways(page.locator(`${shown} pre`))).toBeLessThanOrEqual(0)

    await page.locator(`${body} .file-link`).click()
    const preview = page.locator('[data-testid=file-preview-modal]')
    await expect(preview.locator('.md-preview table')).toBeVisible({ timeout: 10_000 })
    expect(await sideways(preview.locator('.modal-body'))).toBeLessThanOrEqual(0)
    expect(await sideways(preview.locator('.md-preview pre'))).toBeLessThanOrEqual(0)
  })

  // Two fingers (or Ctrl/⌘ + the wheel, which is also how a trackpad pinch arrives) change the
  // size of the text, which lays out again in the width. The size is one value for the notes and
  // the markdown preview, kept on the device.
  test('a pinch or Ctrl + wheel resizes the text; the size is shared with the markdown preview and kept', async ({ page, request }) => {
    await seedSession(request, 'e2e-chat-golden')
    mkdirSync(dirname(NOTE_FILE), { recursive: true })
    mkdirSync(dirname(WIDE_FILE), { recursive: true })
    writeFileSync(NOTE_FILE, `${WIDE_MD}\n${WIDE_FILE}\n`)
    writeFileSync(WIDE_FILE, WIDE_MD)
    await openClient(page, { sid: SID })

    await page.locator('[data-testid=notes-open-button]').click()
    const frame = page.locator(body)
    const content = page.locator(shown)
    await expect(content.locator('table')).toBeVisible()
    expect(await zoomOf(content)).toBe(1)
    const height = await content.evaluate((el) => el.getBoundingClientRect().height)

    // Fingers spread to one and a half times their distance: the text grows as much, and still
    // folds into the width (= the block grows taller, nothing moves sideways).
    await pinch(frame, 100, 150)
    expect(await zoomOf(content)).toBeCloseTo(1.5, 2)
    expect(await content.evaluate((el) => el.getBoundingClientRect().height)).toBeGreaterThan(height)
    expect(await sideways(frame)).toBeLessThanOrEqual(0)

    // Spreading on stops at the upper limit. A table with more columns than fit even with every
    // cell folded to one character is drawn just small enough to fit.
    await pinch(frame, 100, 400)
    expect(await zoomOf(content)).toBe(TEXT_ZOOM_MAX)
    expect(await sideways(frame)).toBeLessThanOrEqual(0)

    // Down to the lower limit, the table's lines stay at least one screen pixel (= a thinner line
    // is not drawn at all).
    await pinch(frame, 400, 100)
    expect(await zoomOf(content)).toBe(TEXT_ZOOM_MIN)
    const line = await content.locator('td').first().evaluate((el) => parseFloat(getComputedStyle(el).borderTopWidth))
    expect(line * TEXT_ZOOM_MIN).toBeGreaterThanOrEqual(1)

    // The wheel with Ctrl: 2 ** (deltaY × 0.002 × 10) per event (= the d3-zoom default).
    await pinch(frame, 50, 100)
    expect(await zoomOf(content)).toBeCloseTo(1, 2)
    await ctrlWheel(frame, -25)
    expect(await zoomOf(content)).toBeCloseTo(Math.SQRT2, 2)

    // The markdown preview opened from the notes shows the same size.
    await page.locator(`${body} .file-link`).click()
    const preview = page.locator('[data-testid=file-preview-modal] .md-preview')
    await expect(preview.locator('table')).toBeVisible({ timeout: 10_000 })
    expect(await zoomOf(preview)).toBeCloseTo(Math.SQRT2, 2)

    // Kept across a reload.
    await page.reload({ waitUntil: 'domcontentloaded' })
    await page.locator('[data-testid=notes-open-button]').click()
    await expect(content.locator('table')).toBeVisible({ timeout: 10_000 })
    expect(await zoomOf(content)).toBeCloseTo(Math.SQRT2, 2)
  })
})
