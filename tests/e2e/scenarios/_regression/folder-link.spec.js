// On a computer a path written in the chat opens as a double click in Finder would (= `POST /file/os-open`), except
// Markdown, which stays in the preview. An iPhone keeps everything in the client. The test backend never opens anything
// on the machine running the tests (= it answers `opened: false`, as a backend that is not a Mac does), so the
// computer's case answers the route here.

import { test, expect } from '@playwright/test'
import { mkdirSync, rmSync, writeFileSync } from 'node:fs'
import { homedir } from 'node:os'
import { join } from 'node:path'
import { seedSession, appendEvent } from '../../helpers/fixture.js'
import { openClient } from '../../helpers/pwa.js'

const SID = 'ses_e2echatgld'

test.describe('regression: a folder link', () => {
  const dir = join(homedir(), '.cache', 'cpc-e2e', 'folder-link')
  const folder = join(dir, 'session_one')
  const note = join(dir, 'plan.md')
  const video = join(dir, 'take.mp4')

  test.beforeEach(async ({ page, request }) => {
    mkdirSync(folder, { recursive: true })
    writeFileSync(note, '# plan\n')
    writeFileSync(video, Buffer.from([0, 0, 0, 0x18, 0x66, 0x74, 0x79, 0x70]))
    const seeded = await seedSession(request, 'e2e-chat-golden')
    appendEvent(seeded.jsonl_path, {
      type: 'assistant',
      uuid: 'a-folder-link',
      message: {
        id: 'msg_folder_link',
        role: 'assistant',
        content: [{ type: 'text', text: `The recording is in \`${folder}/\` as ${video} and the plan is ${note}` }],
        stop_reason: 'end_turn',
        model: 'claude-opus-4-7',
      },
      timestamp: new Date().toISOString(),
    })
    await openClient(page, { sid: SID })
  })

  test.afterEach(() => rmSync(dir, { recursive: true, force: true }))

  test('a computer hands the folder to the backend and stays on the chat', async ({ page, browserName }) => {
    test.skip(browserName !== 'chromium', 'the computer is the desktop browser')
    const asked = []
    await page.route('**/file/os-open', async (route) => {
      asked.push(route.request().postDataJSON())
      await route.fulfill({ json: { opened: true } })
    })
    await page.locator('.file-link', { hasText: 'session_one' }).last().click()
    await expect.poll(() => asked).toEqual([{ path: `${folder}/` }])
    await expect(page.locator('[data-testid=file-tree-modal]')).toHaveCount(0)
    await expect(page.locator('[data-testid=file-preview-modal]')).toHaveCount(0)
  })

  test('a computer opens the tree when the backend is not a Mac', async ({ page, browserName }) => {
    test.skip(browserName !== 'chromium', 'the computer is the desktop browser')
    await page.locator('.file-link', { hasText: 'session_one' }).last().click()
    await expect(page.locator('[data-testid=file-tree-modal]')).toBeVisible()
  })

  test('Markdown stays in the preview and the backend is not asked', async ({ page }) => {
    const asked = []
    page.on('request', (sent) => { if (sent.url().endsWith('/file/os-open')) asked.push(sent.url()) })
    await page.locator('.file-link', { hasText: 'plan.md' }).last().click()
    await expect(page.locator('[data-testid=file-preview-modal]')).toBeVisible()
    expect(asked).toEqual([])
  })

  test('a computer hands a file to the backend and stays on the chat', async ({ page, browserName }) => {
    test.skip(browserName !== 'chromium', 'the computer is the desktop browser')
    const asked = []
    await page.route('**/file/os-open', async (route) => {
      asked.push(route.request().postDataJSON())
      await route.fulfill({ json: { opened: true } })
    })
    await page.locator('.file-link', { hasText: 'take.mp4' }).last().click()
    await expect.poll(() => asked).toEqual([{ path: video }])
    await expect(page.locator('[data-testid=file-preview-modal]')).toHaveCount(0)
  })

  test('a file the screen cannot show says so instead of showing its bytes', async ({ page }) => {
    // the test backend opens nothing, so the computer also falls back to the preview here
    await page.locator('.file-link', { hasText: 'take.mp4' }).last().click()
    const modal = page.locator('[data-testid=file-preview-modal]')
    await expect(modal).toBeVisible()
    await expect(modal.getByText(/cannot be shown here|この画面では開けないファイルです/)).toBeVisible()
  })

  test('an iPhone keeps the tree and does not ask the backend', async ({ page, browserName }) => {
    test.skip(browserName !== 'webkit', 'the iPhone is the mobile WebKit')
    const asked = []
    page.on('request', (sent) => { if (sent.url().endsWith('/file/os-open')) asked.push(sent.url()) })
    await page.locator('.file-link', { hasText: 'session_one' }).last().click()
    await expect(page.locator('[data-testid=file-tree-modal]')).toBeVisible()
    expect(asked).toEqual([])
  })
})
