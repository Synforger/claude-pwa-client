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
import { MAX_PIXEL_SCALE, DOUBLE_TAP_ZOOM, PAN_END_FRICTION } from '../../../frontend/src/features/file-preview/imageZoom.js'

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
// the same pointer events. A gesture is a list of steps played inside the page, each
// stamped with the time the step says (the speed of a flick is read from the time
// between events, so it must not depend on how busy the test machine is).
//   { at: ms from the start, type: 'down' | 'move' | 'up' | 'dblclick', id, x, y }
//   { at: ms from the start, type: 'rest' }   nothing is sent: the fingers stay where they are until then
function play(frame, steps) {
  return frame.evaluate(async (el, list) => {
    const names = { down: 'pointerdown', move: 'pointermove', up: 'pointerup' }
    const t0 = performance.now()
    for (const s of list) {
      const wait = s.at - (performance.now() - t0)
      if (wait > 0) await new Promise((r) => setTimeout(r, wait))
      if (s.type === 'rest') continue
      if (s.type === 'dblclick') {
        // What the browser sends after two quick taps on the same spot.
        el.dispatchEvent(new MouseEvent('dblclick', { clientX: s.x, clientY: s.y, bubbles: true, cancelable: true }))
        continue
      }
      const event = new PointerEvent(names[s.type], {
        pointerId: s.id,
        pointerType: 'touch',
        isPrimary: s.id === 1,
        clientX: s.x,
        clientY: s.y,
        button: 0,
        buttons: s.type === 'up' ? 0 : 1,
        bubbles: true,
        cancelable: true,
      })
      Object.defineProperty(event, 'timeStamp', { value: t0 + s.at })
      el.dispatchEvent(event)
    }
  }, steps)
}

const FRAME_MS = 16
// How long a finger rests before lifting when the gesture should end without speed.
const REST_MS = 150

// One finger from `from`, moved by (dx, dy) over `ms`. `hold` keeps it still before
// lifting; `lift: false` leaves it down, and the gesture still lasts through `hold`
// (the preview reads "lifted from rest" off the time since the last move, so a `lift`
// played afterwards must come that much later, however fast the test gets there).
function drag(from, dx, dy, { ms = 160, hold = 0, lift = true } = {}) {
  const steps = [{ at: 0, type: 'down', id: 1, x: from.x, y: from.y }]
  const count = Math.max(1, Math.round(ms / FRAME_MS))
  for (let i = 1; i <= count; i++) {
    steps.push({ at: (ms * i) / count, type: 'move', id: 1, x: from.x + (dx * i) / count, y: from.y + (dy * i) / count })
  }
  if (lift) steps.push({ at: ms + hold, type: 'up', id: 1, x: from.x + dx, y: from.y + dy })
  else if (hold) steps.push({ at: ms + hold, type: 'rest' })
  return steps
}

// Two fingers level with each other around `center`, from `fromSpan` apart to `toSpan` apart.
function pinch(center, fromSpan, toSpan, { ms = 160, hold = REST_MS, lift = true } = {}) {
  const at = (span) => [center.x - span / 2, center.x + span / 2]
  const [a0, b0] = at(fromSpan)
  const steps = [
    { at: 0, type: 'down', id: 1, x: a0, y: center.y },
    { at: 0, type: 'down', id: 2, x: b0, y: center.y },
  ]
  const count = Math.max(1, Math.round(ms / FRAME_MS))
  for (let i = 1; i <= count; i++) {
    const [a, b] = at(fromSpan + ((toSpan - fromSpan) * i) / count)
    steps.push({ at: (ms * i) / count, type: 'move', id: 1, x: a, y: center.y })
    steps.push({ at: (ms * i) / count, type: 'move', id: 2, x: b, y: center.y })
  }
  if (lift) {
    const [a1, b1] = at(toSpan)
    steps.push({ at: ms + hold, type: 'up', id: 1, x: a1, y: center.y })
    steps.push({ at: ms + hold, type: 'up', id: 2, x: b1, y: center.y })
  } else if (hold) {
    steps.push({ at: ms + hold, type: 'rest' })
  }
  return steps
}

// Lifts the fingers a gesture left down.
function lift(points) {
  return points.map((p, i) => ({ at: 0, type: 'up', id: i + 1, x: p.x, y: p.y }))
}

// Two quick taps on one spot, then the double-click event a browser derives from them.
function doubleTap(point) {
  return [
    { at: 0, type: 'down', id: 1, ...point },
    { at: 40, type: 'up', id: 1, ...point },
    { at: 140, type: 'down', id: 1, ...point },
    { at: 180, type: 'up', id: 1, ...point },
    { at: 185, type: 'dblclick', ...point },
  ]
}

// Where the image is at a few moments from now (one reading every `every` ms).
function watch(img, count, every) {
  return img.evaluate(async (el, a) => {
    const out = []
    for (let i = 0; i < a.count; i++) {
      const b = el.getBoundingClientRect()
      out.push({ left: b.left, top: b.top, right: b.right, bottom: b.bottom, width: b.width, height: b.height })
      await new Promise((r) => setTimeout(r, a.every))
    }
    return out
  }, { count, every })
}

// Waits until the image has stopped moving, and returns where it rests.
async function atRest(img) {
  let last = await box(img)
  await expect.poll(async () => {
    await new Promise((r) => setTimeout(r, 120))
    const now = await box(img)
    const still = Math.abs(now.left - last.left) < 0.05 && Math.abs(now.top - last.top) < 0.05 && Math.abs(now.width - last.width) < 0.05
    last = now
    return still
  }, { timeout: 8000 }).toBe(true)
  return last
}

// The step a double tap takes from the fit, and the times and curve of the motions,
// are constants in the frontend; the scenarios read them from there.

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

  test('fingers zoom around the point between them, move the image, and a move ends where the finger stops', async ({ page, request }) => {
    const paths = await openChatWithImages(page, request, { 'zoom-wide.png': [1600, 1000] })
    try {
      const { modal, frame, img } = await openImage(page, 'zoom-wide.png')
      const view = await box(frame)

      // Opens fitted to the width, at the top of the frame.
      const fit = await box(img)
      expect(fit.width).toBeCloseTo(view.width, 0)
      expect(fit.left).toBeCloseTo(view.left, 0)
      expect(fit.top).toBeCloseTo(view.top, 0)

      // Spreading two fingers to three times as far apart makes the image three
      // times as large, and the place between the fingers stays between them.
      const center = { x: view.left + view.width * 0.25, y: view.top + Math.min(fit.height, view.height) * 0.5 }
      const before = under(fit, center)
      await play(frame, pinch(center, 60, 180))
      const zoomed = await atRest(img)
      expect(zoomed.width).toBeCloseTo(fit.width * 3, 0)
      expect(under(zoomed, center).fx).toBeCloseTo(before.fx, 2)
      await expect(modal).toBeVisible()

      // One finger moves it by the distance the finger moves; resting the finger
      // before lifting leaves the image exactly there.
      const grab = { x: view.left + view.width / 2, y: view.top + view.height / 2 }
      await play(frame, drag(grab, 60, 40, { hold: REST_MS }))
      const moved = await atRest(img)
      expect(moved.left).toBeCloseTo(zoomed.left + 60, 0)
      expect(moved.top).toBeCloseTo(zoomed.top + 40, 0)
      await expect(modal).toBeVisible()

      // Escape still closes the preview.
      await page.keyboard.press('Escape')
      await expect(modal).toHaveCount(0)
    } finally {
      removeImages(paths)
    }
  })

  test('a flick keeps the image gliding, and a finger stops it where it is', async ({ page, request }) => {
    const paths = await openChatWithImages(page, request, { 'zoom-wide.png': [1600, 1000] })
    try {
      const { frame, img } = await openImage(page, 'zoom-wide.png')
      const view = await box(frame)
      const fit = await box(img)
      const center = { x: view.left + view.width / 2, y: view.top + Math.min(fit.height, view.height) / 2 }
      await play(frame, pinch(center, 60, 240))
      const zoomed = await atRest(img)

      // A quick move to the left, lifted without stopping: the image goes on in the
      // same direction after the finger is gone, slows down, and stops inside the frame.
      const grab = { x: view.left + view.width * 0.7, y: view.top + view.height / 2 }
      await play(frame, drag(grab, -80, 0, { ms: 80 }))
      const after = await watch(img, 4, 60)
      expect(after[0].left).toBeLessThan(zoomed.left - 60) // it followed the finger
      expect(after[1].left).toBeLessThan(after[0].left - 1) // and kept going
      expect(after[3].left).toBeLessThan(after[1].left - 1)
      const rest = await atRest(img)
      expect(rest.left).toBeLessThan(after[3].left + 0.5)
      // 80 px in 80 ms is 1 px/ms: it glides on by about 200 px (the speed times r / (1 - r)), no more.
      expect(zoomed.left - 80 - rest.left).toBeGreaterThan(120)
      expect(zoomed.left - 80 - rest.left).toBeLessThan(280)
      expect(rest.right).toBeGreaterThanOrEqual(view.right - 0.5) // still covers the frame
      expect(rest.width).toBeCloseTo(zoomed.width, 0)

      // Flick it back the other way and put a finger down while it is gliding: it stops there.
      await play(frame, drag(grab, 80, 0, { ms: 80 }))
      await page.waitForTimeout(60)
      await play(frame, [{ at: 0, type: 'down', id: 1, x: grab.x, y: grab.y }])
      const caught = await watch(img, 3, 80)
      expect(caught[1].left).toBeCloseTo(caught[0].left, 0)
      expect(caught[2].left).toBeCloseTo(caught[0].left, 0)
      expect(caught[0].left).toBeLessThan(view.left - 1) // caught on the way, not at the end
      await play(frame, lift([grab]))
    } finally {
      removeImages(paths)
    }
  })

  test('pulled past an edge or pinched past a limit, the image gives a little and returns when let go', async ({ page, request }) => {
    const paths = await openChatWithImages(page, request, { 'zoom-wide.png': [1600, 1000] })
    try {
      const { frame, img } = await openImage(page, 'zoom-wide.png')
      const view = await box(frame)
      const fit = await box(img)
      const center = { x: view.left + view.width / 2, y: view.top + Math.min(fit.height, view.height) / 2 }

      // Pinching in at the fit: it gets a little smaller under the fingers ...
      await play(frame, pinch(center, 200, 100, { lift: false }))
      const squeezed = await box(img)
      expect(squeezed.width).toBeLessThan(fit.width - 1)
      expect(squeezed.width).toBeGreaterThan(fit.width * 0.5) // far less than the fingers asked for
      // ... and goes back to the fit when they lift: part of the way first, then all of it.
      await play(frame, lift([{ x: center.x - 50, y: center.y }, { x: center.x + 50, y: center.y }]))
      const returning = await watch(img, 2, 30)
      expect(returning[1].width).toBeGreaterThan(squeezed.width)
      const back = await atRest(img)
      expect(back.width).toBeCloseTo(fit.width, 0)
      expect(back.left).toBeCloseTo(fit.left, 0)

      // Zoomed in, pulled 100 past the left edge: it follows by only part of that ...
      await play(frame, pinch(center, 60, 180))
      await atRest(img)
      const grab = { x: view.left + 20, y: view.top + view.height / 2 }
      await play(frame, drag(grab, 5000, 0, { hold: REST_MS, lift: false }))
      const start = await box(img)
      await play(frame, lift([{ x: grab.x + 5000, y: grab.y }]))
      // (the finger went far beyond the edge; what shows is the overshoot times the resistance)
      expect(start.left).toBeGreaterThan(view.left + 1)
      const gone = await box(img)
      expect(gone.left).toBeLessThanOrEqual(start.left)
      // ... and comes back to rest on its edge.
      const rest = await atRest(img)
      expect(rest.left).toBeCloseTo(view.left, 0)

      // The same pull measured exactly: 100 past the edge shows as 100 times the resistance.
      const edge = await box(img)
      await play(frame, drag(grab, 100, 0, { hold: REST_MS, lift: false }))
      const pulled = await box(img)
      expect(pulled.left - edge.left).toBeCloseTo(100 * PAN_END_FRICTION, 0)
      await play(frame, lift([{ x: grab.x + 100, y: grab.y }]))
      expect((await atRest(img)).left).toBeCloseTo(view.left, 0)
    } finally {
      removeImages(paths)
    }
  })

  test('a double tap moves smoothly one step in, and back to the fit from any zoom', async ({ page, request }) => {
    const paths = await openChatWithImages(page, request, { 'zoom-wide.png': [1600, 1000] })
    try {
      const { modal, frame, img } = await openImage(page, 'zoom-wide.png')
      const view = await box(frame)
      const fit = await box(img)
      const spot = { x: view.left + view.width * 0.75, y: view.top + Math.min(fit.height, view.height) * 0.25 }
      const before = under(fit, spot)

      // Two taps: on the way it is between the two sizes, at the end one step in,
      // with the tapped place still under the finger.
      await play(frame, doubleTap(spot))
      const onTheWay = await watch(img, 2, 90)
      expect(onTheWay[1].width).toBeGreaterThan(fit.width + 1)
      expect(onTheWay[1].width).toBeLessThan(fit.width * DOUBLE_TAP_ZOOM - 1)
      const zoomed = await atRest(img)
      expect(zoomed.width).toBeCloseTo(fit.width * DOUBLE_TAP_ZOOM, 0)
      expect(under(zoomed, spot).fx).toBeCloseTo(before.fx, 2)
      await expect(modal).toBeVisible()

      // Zoom further with the fingers, then two taps: back to the fit, whatever the zoom was.
      await play(frame, pinch(spot, 60, 120))
      expect((await atRest(img)).width).toBeGreaterThan(zoomed.width + 1)
      await play(frame, doubleTap(spot))
      const back = await atRest(img)
      expect(back.width).toBeCloseTo(fit.width, 0)
      expect(back.left).toBeCloseTo(fit.left, 0)
      expect(back.top).toBeCloseTo(fit.top, 0)

      // Two taps again while it is still moving in: it turns back from where it is.
      await play(frame, doubleTap(spot))
      await page.waitForTimeout(100)
      const midway = await box(img)
      await play(frame, doubleTap(spot))
      expect(midway.width).toBeGreaterThan(fit.width + 1)
      expect((await atRest(img)).width).toBeCloseTo(fit.width, 0)
    } finally {
      removeImages(paths)
    }
  })

  test('Ctrl + wheel zooms around the cursor, a plain wheel scrolls, and a mouse drag stops at the edge', async ({ page, request, isMobile }) => {
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

      // A plain wheel scrolls the fitted image, and stops at the bottom.
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

      // Dragging with the mouse moves the zoomed image by the same distance, and it
      // stays where the button was released (no glide for a mouse).
      await page.mouse.down()
      await page.mouse.move(cursor.x + 80, cursor.y + 50, { steps: 5 })
      await page.mouse.up()
      const dragged = await watch(img, 3, 60)
      expect(dragged[0].left).toBeCloseTo(zoomed.left + 80, 0)
      expect(dragged[0].top).toBeCloseTo(zoomed.top + 50, 0)
      expect(dragged[2].left).toBeCloseTo(dragged[0].left, 1)

      // Dragged far past the edge, a mouse stops at the edge while the button is still down.
      await page.mouse.down()
      await page.mouse.move(cursor.x + 5000, cursor.y + 5000, { steps: 5 })
      const held = await box(img)
      expect(held.left).toBeCloseTo(view.left, 0)
      expect(held.top).toBeCloseTo(view.top, 0)
      await page.mouse.up()
      await expect(modal).toBeVisible()

      // Zooming out stops at the fit; it never gets smaller.
      await page.mouse.move(cursor.x, cursor.y)
      await page.keyboard.down('Control')
      await page.mouse.wheel(0, 100_000)
      await expect.poll(async () => (await box(img)).width).toBeCloseTo(fit.width, 0)
      await page.keyboard.up('Control')

      // A double click takes the same step as a double tap, and back.
      await frame.dblclick({ position: { x: view.width / 2, y: 80 } })
      expect((await atRest(img)).width).toBeCloseTo(fit.width * DOUBLE_TAP_ZOOM, 0)
      await frame.dblclick({ position: { x: view.width / 2, y: 80 } })
      expect((await atRest(img)).width).toBeCloseTo(fit.width, 0)

      // The close button still closes the preview.
      await modal.locator('.modal-close').click()
      await expect(modal).toHaveCount(0)
    } finally {
      removeImages(paths)
    }
  })

  test('a trackpad pinch that arrives as gesture events zooms around the pointer', async ({ page, request }) => {
    // Safari on macOS reports a trackpad pinch as gesturestart / gesturechange / gestureend
    // (a centre and a scale relative to the start) instead of Ctrl + wheel. The browsers
    // under test cannot make that gesture, so the events are sent as Safari shapes them.
    const paths = await openChatWithImages(page, request, { 'zoom-wide.png': [1600, 1000] })
    try {
      const { modal, frame, img } = await openImage(page, 'zoom-wide.png')
      const view = await box(frame)
      const fit = await box(img)
      const pointer = { x: view.left + view.width * 0.25, y: view.top + Math.min(fit.height, view.height) * 0.5 }
      const send = (type, scale) => frame.evaluate((el, a) => {
        const event = new Event(a.type, { bubbles: true, cancelable: true })
        Object.assign(event, { scale: a.scale, clientX: a.x, clientY: a.y })
        el.dispatchEvent(event)
        return event.defaultPrevented
      }, { type, scale, x: pointer.x, y: pointer.y })

      const before = under(fit, pointer)
      // The page itself must not zoom: the preview takes the gesture.
      expect(await send('gesturestart', 1)).toBe(true)
      expect(await send('gesturechange', 1.4)).toBe(true)
      await send('gesturechange', 2.5)
      await send('gestureend', 2.5)
      const zoomed = await box(img)
      expect(zoomed.width).toBeCloseTo(fit.width * 2.5, 0)
      expect(under(zoomed, pointer).fx).toBeCloseTo(before.fx, 2)

      // Pinching back in stops at the fit (a trackpad does not go past the limits).
      await send('gesturestart', 1)
      await send('gesturechange', 0.1)
      expect((await box(img)).width).toBeCloseTo(fit.width, 0)
      await send('gestureend', 0.1)
      const back = await box(img)
      expect(back.width).toBeCloseTo(fit.width, 0)
      expect(back.left).toBeCloseTo(fit.left, 0)
      await expect(modal).toBeVisible()
    } finally {
      removeImages(paths)
    }
  })

  test('a small image steps in on a double tap, and comes back from past the zoom limit', async ({ page, request }) => {
    const paths = await openChatWithImages(page, request, { 'zoom-small.png': [2, 2] })
    try {
      const { frame, img } = await openImage(page, 'zoom-small.png')
      const view = await box(frame)
      const fit = await box(img)
      expect(fit.width).toBeCloseTo(2, 1)
      const center = { x: view.left + view.width / 2, y: view.top + 1 }

      // The step is relative to the fit, whatever the pixel count: 2 px becomes 2 x the step.
      await play(frame, doubleTap(center))
      expect((await atRest(img)).width).toBeCloseTo(2 * DOUBLE_TAP_ZOOM, 1)

      // Spreading the fingers far past the limit shows a little more than the limit, and
      // letting go brings it back to the limit.
      await play(frame, pinch(center, 20, 400, { lift: false }))
      const stretched = await box(img)
      expect(stretched.width).toBeGreaterThan(2 * MAX_PIXEL_SCALE)
      await play(frame, lift([{ x: center.x - 200, y: center.y }, { x: center.x + 200, y: center.y }]))
      expect((await atRest(img)).width).toBeCloseTo(2 * MAX_PIXEL_SCALE, 1)

      await play(frame, doubleTap(center))
      expect((await atRest(img)).width).toBeCloseTo(2, 1)
    } finally {
      removeImages(paths)
    }
  })

  test('a tall image scrolls at the fit and glides after a flick, and another image opens fitted', async ({ page, request }) => {
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

      // One finger scrolls the fitted image by the distance it moves.
      const grab = { x: view.left + view.width / 2, y: view.top + view.height * 0.8 }
      await play(frame, drag(grab, 0, -200, { hold: REST_MS }))
      const scrolled = await atRest(img)
      expect(scrolled.top).toBeCloseTo(fit.top - 200, 0)
      expect(scrolled.width).toBeCloseTo(300, 0)

      // A flick keeps it going after the finger lifts, like a page.
      await play(frame, drag(grab, 0, -80, { ms: 80 }))
      const after = await watch(img, 3, 60)
      expect(after[1].top).toBeLessThan(after[0].top - 1)
      const rest = await atRest(img)
      expect(rest.top).toBeLessThan(scrolled.top - 100)
      expect(rest.left).toBeCloseTo(fit.left, 0)

      // A hard flick near the end stops on the last row.
      let end = await atRest(img)
      for (let i = 0; i < 8 && end.bottom > view.bottom + 0.5; i++) {
        await play(frame, drag(grab, 0, -300, { ms: 60 }))
        end = await atRest(img)
      }
      expect(end.bottom).toBeCloseTo(view.bottom, 0)

      // Zoom it, close it, open another image: the other one starts fitted.
      await play(frame, pinch(grab, 60, 180))
      expect((await atRest(img)).width).toBeCloseTo(900, 0)
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
