// Golden path: file-preview feature.
// Inject a favorites entry pointing at the repo's own README, open the
// favorites quick picker, click the entry, assert the preview modal mounts
// with the right path.

import { test, expect } from '@playwright/test'
import { mkdirSync, rmSync, writeFileSync } from 'node:fs'
import { homedir } from 'node:os'
import { join } from 'node:path'
import { seedSession, appendEvent } from '../../helpers/fixture.js'
import { openClient } from '../../helpers/pwa.js'
import { testCard } from '../../helpers/png.js'
// The zoom limit is one constant in the frontend; the scenarios read it from there
// so that changing the limit does not mean editing a number here.
import { MAX_PIXEL_SCALE } from '../../../frontend/src/features/file-preview/imageZoom.js'

const SID = 'ses_e2echatgld'

// /file/raw only serves files under HOME, and the worktree running e2e may live
// outside it, so sample images are written under ~/.cache for the test.
const IMAGE_DIR = join(homedir(), '.cache', 'cpc-e2e')

// Seeds a chat whose last message names the given images, and opens the client.
// images: { '<file name>': [width, height] } -> { '<file name>': '<absolute path>' }
async function openChatWithImages(page, request, images) {
  mkdirSync(IMAGE_DIR, { recursive: true })
  const paths = {}
  for (const [name, [width, height]] of Object.entries(images)) {
    paths[name] = join(IMAGE_DIR, name)
    writeFileSync(paths[name], testCard(width, height))
  }
  const seeded = await seedSession(request, 'e2e-chat-golden')
  appendEvent(seeded.jsonl_path, {
    type: 'assistant',
    uuid: 'a-image-zoom',
    message: {
      id: 'msg_image_zoom',
      role: 'assistant',
      content: [{ type: 'text', text: Object.values(paths).join('\n\n') }],
      stop_reason: 'end_turn',
      model: 'claude-opus-4-7',
    },
    timestamp: new Date().toISOString(),
  })
  await openClient(page, { sid: SID })
  return paths
}

// Opens one image from the chat and waits until it is laid out in the preview.
async function openImage(page, name) {
  await page.locator('.file-link', { hasText: name }).last().click()
  const modal = page.locator('[data-testid=file-preview-modal]')
  await expect(modal).toBeVisible({ timeout: 10_000 })
  const frame = modal.locator('[data-testid=file-preview-image-frame]')
  const img = modal.locator('[data-testid=file-preview-image]')
  await expect(img).toBeVisible()
  await expect(modal.getByText('Loading...')).toHaveCount(0)
  return { modal, frame, img }
}

function box(locator) {
  return locator.evaluate((el) => {
    const b = el.getBoundingClientRect()
    return { left: b.left, top: b.top, right: b.right, bottom: b.bottom, width: b.width, height: b.height }
  })
}

// Where in the image (as a fraction of its width / height) a viewport point lands.
function under(imgBox, point) {
  return { fx: (point.x - imgBox.left) / imgBox.width, fy: (point.y - imgBox.top) / imgBox.height }
}

// Fingers are sent as pointer events on the frame: the browsers under test have no
// multi-touch input of their own, and the preview handles mouse and touch through
// the same pointer events.
function finger(frame, type, id, point) {
  return frame.evaluate((el, a) => {
    el.dispatchEvent(new PointerEvent(a.type, {
      pointerId: a.id,
      pointerType: 'touch',
      isPrimary: a.id === 1,
      clientX: a.x,
      clientY: a.y,
      button: 0,
      buttons: a.type === 'pointerup' ? 0 : 1,
      bubbles: true,
      cancelable: true,
    }))
  }, { type, id, x: point.x, y: point.y })
}

// Two fingers level with each other around `center`, moving from `fromSpan` apart to `toSpan` apart.
async function pinch(frame, center, fromSpan, toSpan, steps = 8) {
  const at = (span) => [
    { x: center.x - span / 2, y: center.y },
    { x: center.x + span / 2, y: center.y },
  ]
  const [a0, b0] = at(fromSpan)
  await finger(frame, 'pointerdown', 1, a0)
  await finger(frame, 'pointerdown', 2, b0)
  for (let i = 1; i <= steps; i++) {
    const [a, b] = at(fromSpan + ((toSpan - fromSpan) * i) / steps)
    await finger(frame, 'pointermove', 1, a)
    await finger(frame, 'pointermove', 2, b)
  }
  const [a1, b1] = at(toSpan)
  await finger(frame, 'pointerup', 1, a1)
  await finger(frame, 'pointerup', 2, b1)
}

// One finger from `from`, moved by (dx, dy).
async function swipe(frame, from, dx, dy, steps = 8) {
  await finger(frame, 'pointerdown', 1, from)
  for (let i = 1; i <= steps; i++) {
    await finger(frame, 'pointermove', 1, { x: from.x + (dx * i) / steps, y: from.y + (dy * i) / steps })
  }
  await finger(frame, 'pointerup', 1, { x: from.x + dx, y: from.y + dy })
}

// Screenshots for a human to look at (fit / zoomed / moved to the edge). They go to
// the test's own output folder, or to CPC_E2E_SHOT_DIR when that is set.
async function shot(page, testInfo, name) {
  const dir = process.env.CPC_E2E_SHOT_DIR
  const file = `${testInfo.project.name}-${name}.png`
  if (dir) mkdirSync(dir, { recursive: true })
  await page.screenshot({ path: dir ? join(dir, file) : testInfo.outputPath(file) })
}

function removeImages(paths) {
  for (const path of Object.values(paths)) rmSync(path, { force: true })
}

test.describe('golden: file-preview', () => {
  test('preview modal opens from favorites quick picker', async ({ page, request }) => {
    await seedSession(request, 'e2e-chat-golden')
    await openClient(page, { sid: SID })

    // Pin a favorite to a file the backend will happily serve under HOME.
    const fixturePath = process.env.HOME + '/repos/claude-pwa-client.v2/README.md'
    await page.evaluate((path) => {
      localStorage.setItem('cpc.fileTree.favorites', JSON.stringify([{ path, name: 'README.md' }]))
      window.dispatchEvent(new CustomEvent('cpc-favorites-changed'))
    }, fixturePath)
    await page.reload({ waitUntil: 'domcontentloaded' })
    await page.locator('[data-testid=chat-input]').waitFor({ state: 'visible' })
    await page.waitForTimeout(1500)

    await page.locator('[data-testid=favorites-open-button]').click()
    // The favorites picker shows the pinned row; click it.
    await page.getByText('README.md').first().click()

    const modal = page.locator('[data-testid=file-preview-modal]')
    await expect(modal).toBeVisible({ timeout: 10_000 })
    await expect(modal.locator('[data-testid=file-preview-path]')).toContainText('README.md')
  })

  test('an image path in the chat opens as an image', async ({ page, request }) => {
    // /file/raw only serves files under HOME, and the worktree running e2e may live
    // outside it, so the sample image is written under ~/.cache for this test.
    const dir = join(homedir(), '.cache', 'cpc-e2e')
    const png = join(dir, 'preview-sample.png')
    mkdirSync(dir, { recursive: true })
    writeFileSync(png, Buffer.from(
      'iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAYAAABytg0kAAAAEUlEQVR4nGP4z8DwH4QZYAwAR8oH+WdZbrcAAAAASUVORK5CYII=',
      'base64',
    ))
    try {
      const seeded = await seedSession(request, 'e2e-chat-golden')
      appendEvent(seeded.jsonl_path, {
        type: 'assistant',
        uuid: 'a-image-preview',
        message: {
          id: 'msg_image_preview',
          role: 'assistant',
          content: [{ type: 'text', text: `Saved the screenshot to ${png}` }],
          stop_reason: 'end_turn',
          model: 'claude-opus-4-7',
        },
        timestamp: new Date().toISOString(),
      })
      await openClient(page, { sid: SID })

      await page.locator('.file-link', { hasText: 'preview-sample.png' }).last().click()
      const modal = page.locator('[data-testid=file-preview-modal]')
      await expect(modal).toBeVisible({ timeout: 10_000 })
      const img = modal.locator('[data-testid=file-preview-image]')
      await expect(img).toBeVisible()
      await expect.poll(() => img.evaluate((el) => el.naturalWidth)).toBe(2)
      // The loading label goes away once the image is in (a cached image can load
      // before the preview's own reset runs).
      await expect(modal.getByText('Loading...')).toHaveCount(0)
    } finally {
      rmSync(png, { force: true })
    }
  })

  test('an image zooms around the fingers, moves within the frame, and a double click toggles fit and actual size', async ({ page, request }, testInfo) => {
    const paths = await openChatWithImages(page, request, { 'zoom-wide.png': [1600, 1000] })
    try {
      const { modal, frame, img } = await openImage(page, 'zoom-wide.png')
      const view = await box(frame)

      // Opens fitted to the width, at the top of the frame.
      const fit = await box(img)
      expect(fit.width).toBeCloseTo(view.width, 0)
      expect(fit.left).toBeCloseTo(view.left, 0)
      expect(fit.top).toBeCloseTo(view.top, 0)
      await shot(page, testInfo, '1-fit')

      // Spreading two fingers to three times as far apart makes the image three
      // times as large, and the place between the fingers stays between them.
      const center = { x: view.left + view.width * 0.25, y: view.top + Math.min(fit.height, view.height) * 0.5 }
      const before = under(fit, center)
      await pinch(frame, center, 60, 180)
      const zoomed = await box(img)
      expect(zoomed.width).toBeCloseTo(fit.width * 3, 0)
      expect(under(zoomed, center).fx).toBeCloseTo(before.fx, 2)
      await expect(modal).toBeVisible()
      await shot(page, testInfo, '2-zoomed')

      // One finger moves it, and it stops when its edge reaches the frame's edge:
      // dragged far down-right it rests on its top-left corner, far up-left on its
      // bottom-right corner.
      const grab = { x: view.left + view.width / 2, y: view.top + view.height / 2 }
      await swipe(frame, grab, 5000, 5000)
      const topLeft = await box(img)
      expect(topLeft.left).toBeCloseTo(view.left, 0)
      expect(topLeft.top).toBeCloseTo(view.top, 0)
      await swipe(frame, grab, -5000, -5000)
      const bottomRight = await box(img)
      expect(bottomRight.width).toBeCloseTo(zoomed.width, 0)
      expect(bottomRight.right).toBeCloseTo(view.right, 0)
      expect(bottomRight.height).toBeGreaterThan(view.height)
      expect(bottomRight.bottom).toBeCloseTo(view.bottom, 0)
      await expect(modal).toBeVisible()
      await shot(page, testInfo, '3-edge')

      // A double click while zoomed goes back to the fit.
      await frame.dblclick({ position: { x: view.width / 2, y: view.height / 2 } })
      const again = await box(img)
      expect(again.width).toBeCloseTo(fit.width, 0)
      expect(again.left).toBeCloseTo(fit.left, 0)
      expect(again.top).toBeCloseTo(fit.top, 0)

      // A double click at the fit goes to actual size (one image pixel per point),
      // keeping the clicked place under the pointer.
      const spot = { x: view.width * 0.75, y: Math.min(fit.height, view.height) * 0.25 }
      const clicked = { x: view.left + spot.x, y: view.top + spot.y }
      const beforeClick = under(again, clicked)
      await frame.dblclick({ position: spot })
      const actual = await box(img)
      expect(actual.width).toBeCloseTo(1600, 0)
      expect(under(actual, clicked).fx).toBeCloseTo(beforeClick.fx, 2)
      expect(under(actual, clicked).fy).toBeCloseTo(beforeClick.fy, 2)

      // Escape still closes the preview.
      await page.keyboard.press('Escape')
      await expect(modal).toHaveCount(0)
    } finally {
      removeImages(paths)
    }
  })

  test('Ctrl + wheel zooms around the cursor, a plain wheel scrolls, and a mouse drag moves the image', async ({ page, request, isMobile }) => {
    test.skip(isMobile, 'mouse wheel and mouse drag are desktop input')
    const paths = await openChatWithImages(page, request, { 'zoom-wide.png': [1600, 1000] })
    try {
      const { modal, frame, img } = await openImage(page, 'zoom-wide.png')
      const view = await box(frame)
      const fit = await box(img)
      // At this width the fitted image is taller than the frame, so there is something to scroll.
      expect(fit.height).toBeGreaterThan(view.height)

      const cursor = { x: view.left + view.width * 0.3, y: view.top + view.height * 0.6 }
      await page.mouse.move(cursor.x, cursor.y)

      // A plain wheel scrolls the fitted image, as it did before zoom existed, and stops at the bottom.
      await page.mouse.wheel(0, 100)
      await expect.poll(async () => (await box(img)).top).toBeCloseTo(fit.top - 100, 0)
      expect((await box(img)).width).toBeCloseTo(fit.width, 0)
      await page.mouse.wheel(0, 100_000)
      await expect.poll(async () => (await box(img)).bottom).toBeCloseTo(view.bottom, 0)
      await page.mouse.wheel(0, -100_000)
      await expect.poll(async () => (await box(img)).top).toBeCloseTo(fit.top, 0)

      // Ctrl + wheel zooms in, keeping the place under the cursor.
      const before = under(await box(img), cursor)
      await page.keyboard.down('Control')
      await page.mouse.wheel(0, -60)
      await expect.poll(async () => (await box(img)).width).toBeGreaterThan(fit.width * 1.5)
      const zoomed = await box(img)
      expect(under(zoomed, cursor).fx).toBeCloseTo(before.fx, 2)
      expect(under(zoomed, cursor).fy).toBeCloseTo(before.fy, 2)
      await page.keyboard.up('Control')

      // Dragging with the mouse moves the zoomed image by the same distance.
      await page.mouse.down()
      await page.mouse.move(cursor.x + 80, cursor.y + 50, { steps: 5 })
      await page.mouse.up()
      const dragged = await box(img)
      expect(dragged.left).toBeCloseTo(zoomed.left + 80, 0)
      expect(dragged.top).toBeCloseTo(zoomed.top + 50, 0)
      await expect(modal).toBeVisible()

      // Zooming out stops at the fit; it never gets smaller.
      await page.keyboard.down('Control')
      await page.mouse.wheel(0, 100_000)
      await expect.poll(async () => (await box(img)).width).toBeCloseTo(fit.width, 0)
      await page.keyboard.up('Control')

      // The close button still closes the preview.
      await modal.locator('.modal-close').click()
      await expect(modal).toHaveCount(0)
    } finally {
      removeImages(paths)
    }
  })

  test('a small image goes to the zoom limit on a double click and never shrinks below its own size', async ({ page, request }) => {
    const paths = await openChatWithImages(page, request, { 'zoom-small.png': [2, 2] })
    try {
      const { frame, img } = await openImage(page, 'zoom-small.png')
      const view = await box(frame)
      const fit = await box(img)
      expect(fit.width).toBeCloseTo(2, 1)

      // Pinching in at the fit changes nothing.
      const center = { x: view.left + view.width / 2, y: view.top + view.height / 2 }
      await pinch(frame, center, 200, 40)
      expect((await box(img)).width).toBeCloseTo(2, 1)

      // Actual size is no larger than the fit here, so a double click goes to the limit.
      await frame.dblclick({ position: { x: view.width / 2, y: 1 } })
      expect((await box(img)).width).toBeCloseTo(2 * MAX_PIXEL_SCALE, 1)

      // Spreading the fingers further does not pass the limit.
      await pinch(frame, center, 40, 400)
      expect((await box(img)).width).toBeCloseTo(2 * MAX_PIXEL_SCALE, 1)

      await frame.dblclick({ position: { x: view.width / 2, y: 1 } })
      expect((await box(img)).width).toBeCloseTo(2, 1)
    } finally {
      removeImages(paths)
    }
  })

  test('a tall image scrolls at the fit, and another image opens fitted', async ({ page, request }) => {
    const paths = await openChatWithImages(page, request, {
      'zoom-tall.png': [300, 4000],
      'zoom-wide.png': [1600, 1000],
    })
    try {
      const { modal, frame, img } = await openImage(page, 'zoom-tall.png')
      const view = await box(frame)
      const fit = await box(img)
      expect(fit.width).toBeCloseTo(300, 0)
      expect(fit.top).toBeCloseTo(view.top, 0)

      // One finger scrolls the fitted image by the distance it moves, down to its last row.
      const grab = { x: view.left + view.width / 2, y: view.top + view.height * 0.8 }
      await swipe(frame, grab, 0, -200)
      const scrolled = await box(img)
      expect(scrolled.top).toBeCloseTo(fit.top - 200, 0)
      expect(scrolled.width).toBeCloseTo(300, 0)
      await swipe(frame, grab, 0, -100_000)
      expect((await box(img)).bottom).toBeCloseTo(view.bottom, 0)

      // Zoom it, close it, open another image: the other one starts fitted.
      await pinch(frame, grab, 60, 180)
      expect((await box(img)).width).toBeCloseTo(900, 0)
      await modal.locator('.modal-close').click()
      await expect(modal).toHaveCount(0)

      const next = await openImage(page, 'zoom-wide.png')
      const nextView = await box(next.frame)
      const nextFit = await box(next.img)
      expect(nextFit.width).toBeCloseTo(nextView.width, 0)
      expect(nextFit.top).toBeCloseTo(nextView.top, 0)
    } finally {
      removeImages(paths)
    }
  })
})
