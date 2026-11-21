// Golden path: a request one tab keeps as a ticket shows on the operator's screen. The number on the menu button counts the tickets
// that want a look and the first row of the tab list opens the list; the list names each one's request, what it asks, who holds it and how long ago it moved; the ticket
// screen pins the operator's original words and draws the lines as plain text; answering it moves the ticket out of the
// first group; and a ticket handed over reaches the chat as one line that opens the ticket.
//
// The waiting group, the due dates and the marks come from tickets made through the doors (`due` when a ticket opens or is added to,
// `waiting` on an added line): the backend works the marks out. The marks that need days of silence (`waiting_stale`, `idle`)
// are drawn in the unit tests; the operator's origin needs the operator's words from a tab's record, so it is there too.
//
// The e2e backend has no Claude process: the tickets are made through the backend's own doors (= what `tabs ticket` calls),
// and the answer is written and queued as it is in production. Whether the answer then reaches a tab is not what is
// looked at here (= backend/tests/tickets).

import { test, expect } from '@playwright/test'
import { seedSession } from '../../helpers/fixture.js'
import { openClient } from '../../helpers/pwa.js'

// The list of tickets opens from the first row of the tab list (the menu button holds only the number).
async function openTicketList(page) {
  await page.locator('[data-testid=drawer-toggle]').click()
  await page.locator('[data-testid=drawer-tickets-open]').click()
}

const TITLE = 'Fix the wrapped title'
const REQUEST = 'The title wraps on page 3 <b>of</b> the sample deck.\nPlease keep it on one line.'

async function openTicket(request, sender, { title = TITLE, due = '' } = {}) {
  const opened = await request.post('/tickets', { form: { from: sender, title, text: REQUEST, due } })
  expect(opened.ok()).toBeTruthy()
  const { id } = await opened.json()
  return id
}

// A day as the backend writes it (YYYY-MM-DD, the day of this machine), `days` from today.
function dayFromToday(days) {
  const day = new Date()
  day.setDate(day.getDate() + days)
  return [day.getFullYear(), String(day.getMonth() + 1).padStart(2, '0'), String(day.getDate()).padStart(2, '0')].join('-')
}

async function setAside(request, id, sender, text = 'Waiting for the sample deck') {
  const res = await request.post(`/tickets/${id}/entries`, { form: { from: sender, text, waiting: true } })
  expect(res.ok()).toBeTruthy()
}

// Close the tickets a scenario made, so the next project run on this backend starts with nothing that wants a look.
async function closeAll(request, tickets) {
  for (const [id, sender] of tickets) {
    const res = await request.post(`/tickets/${id}/close`, { form: { from: sender, text: 'Done' } })
    expect(res.ok()).toBeTruthy()
  }
}

async function ask(request, id, sender) {
  const res = await request.post(`/tickets/${id}/asks`, {
    form: { from: sender, kind: 'decide', text: 'One line or two?\n\n- `one line`: shorter title\n- `two lines`: keeps every word', recommend: 'One line' },
  })
  expect(res.ok()).toBeTruthy()
}

test.describe('golden: tickets', () => {
  test('the menu button counts the tickets that want a look, and the list and the ticket screen show them', async ({ page, request }, testInfo) => {
    const tab = await seedSession(request, 'e2e-tab-a')
    await openClient(page, { sid: tab.sid })
    await expect(page.locator('[data-testid=tickets-count]')).toHaveCount(0)

    const id = await openTicket(request, tab.sid)
    await expect(page.locator('[data-testid=tickets-count]')).toHaveCount(0)   // open and held: nothing to look at
    await ask(request, id, tab.sid)
    await expect(page.locator('[data-testid=tickets-count]')).toHaveText('1', { timeout: 20_000 })
    await page.screenshot({ path: testInfo.outputPath('tickets-count.png') })
    const bandWide = page.viewportSize()
    await page.setViewportSize({ width: 390, height: 844 })
    await expect(page.locator('[data-testid=tickets-count]')).toBeVisible()
    await page.screenshot({ path: testInfo.outputPath('tickets-count-narrow.png') })
    await page.setViewportSize(bandWide)

    // The first row of the tab list names the tickets too, at both widths; it opens the list.
    await page.locator('[data-testid=drawer-toggle]').click()
    const listRow = page.locator('[data-testid=drawer-tickets-open]')
    await expect(listRow).toContainText('1')
    await page.screenshot({ path: testInfo.outputPath('tickets-drawer-row.png') })
    const wide = page.viewportSize()
    await page.setViewportSize({ width: 390, height: 844 })
    await expect(listRow).toBeVisible()
    await page.screenshot({ path: testInfo.outputPath('tickets-drawer-row-narrow.png') })
    await page.setViewportSize(wide)
    await listRow.click()
    const group = page.locator('[data-testid=ticket-group-attention]')
    await expect(group).toContainText(TITLE)
    await expect(group.locator(`[data-ticket="${id}"]`)).toHaveCount(1)
    await expect(group).toContainText('Decide')
    await expect(group).toContainText('tab A')
    await page.screenshot({ path: testInfo.outputPath('tickets-list.png') })

    await group.locator(`[data-ticket="${id}"]`).click()
    await expect(page.locator('[data-testid=ticket-heading]')).toContainText(TITLE)
    const asked = page.locator('[data-testid=ticket-entry][data-kind=asked]')
    await expect(asked).toContainText('One line or two?')          // the question and the recommendation, once, among the lines
    await expect(asked).toContainText('One line')
    await expect(page.locator('[data-testid=ticket-answer-box]')).not.toContainText('One line or two?')
    await expect(asked.locator('li')).toHaveCount(2)                 // drawn as Markdown, the way the chat draws it
    const opened = page.locator('[data-testid=ticket-entry][data-kind=opened]')
    await expect(opened).toContainText('<b>of</b>')            // plain text: the markup is shown, not drawn
    await expect(opened.locator('b')).toHaveCount(0)
    await page.screenshot({ path: testInfo.outputPath('tickets-screen.png') })

    // The same screen at a phone's width.
    await page.setViewportSize({ width: 390, height: 844 })
    await expect(page.locator('[data-testid=ticket-answer-box]')).toBeVisible()
    await page.screenshot({ path: testInfo.outputPath('tickets-screen-narrow.png') })

    // Answer with the recommendation: the ticket leaves the first group and the number goes.
    await page.locator('[data-testid=ticket-answer-recommend]').click()
    await expect(page.locator('[data-testid=ticket-answer-box]')).toHaveCount(0, { timeout: 20_000 })
    await expect(page.locator('[data-testid=ticket-entry][data-kind=answered]')).toContainText('One line')
    await page.locator('[data-testid=ticket-close]').click()
    await expect(page.locator('[data-testid=tickets-count]')).toHaveCount(0, { timeout: 20_000 })
    await page.screenshot({ path: testInfo.outputPath('tickets-answered.png') })
  })

  test('a draft stays when the ticket screen is closed and opened again', async ({ page, request }) => {
    const tab = await seedSession(request, 'e2e-tab-a')
    await openClient(page, { sid: tab.sid })
    const id = await openTicket(request, tab.sid)
    try {
      await ask(request, id, tab.sid)
      await page.goto(`/?ses=${encodeURIComponent(tab.sid)}&ticket=${encodeURIComponent(id)}`, { waitUntil: 'domcontentloaded' })
      const field = page.locator('[data-testid=ticket-answer-field]')
      await field.fill('Let me think about it')
      await page.locator('[data-testid=ticket-close]').click()
      await openTicketList(page)
      await page.locator(`[data-testid=ticket-row][data-ticket="${id}"]`).click()
      await expect(field).toHaveValue('Let me think about it')
    } finally {
      await closeAll(request, [[id, tab.sid]])   // it still waits for the operator's answer, which the next project's first scenario must not see
    }
  })

  test('a ticket handed to a tab shows in its chat as one line that opens the ticket', async ({ page, request }, testInfo) => {
    const sender = await seedSession(request, 'e2e-tab-a')
    const receiver = await seedSession(request, 'e2e-tab-b')
    const id = await openTicket(request, sender.sid)
    await openClient(page, { sid: receiver.sid })

    const passed = await request.post(`/tickets/${id}/pass`, { form: { from: sender.sid, to: 'tab B' } })
    expect(passed.ok()).toBeTruthy()
    const link = page.locator('[data-testid=relayed-ticket-link]')
    await expect(link).toContainText(id, { timeout: 20_000 })
    await expect(page.locator('[data-testid=session-held-ticket]')).toHaveCount(0)   // the drawer is closed until opened
    await page.screenshot({ path: testInfo.outputPath('tickets-chat-line.png') })

    await link.click()
    await expect(page.locator('[data-testid=ticket-heading]')).toContainText(TITLE)
  })

  test('the list has the waiting group, a mark and a due date on the rows, and the tab list shows the pause sign', async ({ page, request }, testInfo) => {
    const tab = await seedSession(request, 'e2e-tab-a')
    // One tab holds one ticket each, so each line under a tab reads whole (a line is cut at the width of the list).
    const holders = { run: await seedSession(request, 'e2e-send-empty'), wait: await seedSession(request, 'e2e-reconcile-empty'), plain: await seedSession(request, 'e2e-chat-basic') }
    const run = `Due soon ${Date.now()}`, wait = `Set aside ${Date.now()}`, plain = `Plain wait ${Date.now()}`, late = `Late ask ${Date.now()}`, done = `Done ${Date.now()}`

    const overdueId = await openTicket(request, tab.sid, { title: late, due: dayFromToday(-2) })
    await ask(request, overdueId, tab.sid)
    const dueSoonId = await openTicket(request, holders.run.sid, { title: run, due: dayFromToday(1) })
    const waitId = await openTicket(request, holders.wait.sid, { title: wait, due: dayFromToday(1) })
    await setAside(request, waitId, holders.wait.sid)
    const plainId = await openTicket(request, holders.plain.sid, { title: plain })
    await setAside(request, plainId, holders.plain.sid)
    const doneId = await openTicket(request, tab.sid, { title: done })
    await closeAll(request, [[doneId, tab.sid]])

    const made = [[overdueId, tab.sid], [dueSoonId, holders.run.sid], [waitId, holders.wait.sid], [plainId, holders.plain.sid]]
    try {
      await openClient(page, { sid: tab.sid })
      await page.locator('[data-testid=drawer-toggle]').click()
      const heldOf = (holder) => page.locator(`[data-cpc-sid="${holder.sid}"] [data-testid=session-held-ticket]`)
      await expect(heldOf(holders.wait)).toHaveText(`🎫 ⏸ ⏰ ${wait}`, { timeout: 20_000 })
      await expect(heldOf(holders.plain)).toHaveText(`🎫 ⏸ ${plain}`)
      await expect(heldOf(holders.run)).toHaveText(`🎫 ⏰ ${run}`)
      await page.screenshot({ path: testInfo.outputPath('tickets-held-lines.png') })
      await page.setViewportSize({ width: 390, height: 844 })
      await expect(heldOf(holders.wait)).toBeVisible()
      await page.screenshot({ path: testInfo.outputPath('tickets-held-lines-narrow.png') })
      await page.setViewportSize({ width: 1280, height: 800 })

      // A tab's line opens the list of only the tickets that tab holds
      await heldOf(holders.wait).click()
      await expect(page.locator('[data-testid=ticket-row]')).toHaveCount(1)
      await expect(page.locator(`[data-testid=ticket-row][data-ticket="${waitId}"]`)).toHaveCount(1)
      await page.locator('[data-testid=ticket-drawer-close]').click()
      await page.locator('[data-testid=drawer-toggle]').click()

      await page.locator('[data-testid=drawer-tickets-open]').click()
      const groups = page.locator('[data-testid^=ticket-group-]:not([data-testid=ticket-group-toggle])')
      await expect(groups).toHaveCount(4)
      expect(await groups.evaluateAll((els) => els.map((el) => el.dataset.testid)))
        .toEqual(['ticket-group-attention', 'ticket-group-running', 'ticket-group-waiting', 'ticket-group-closed'])

      const rowOf = (group, id) => page.locator(`[data-testid=ticket-group-${group}] [data-ticket="${id}"]`)
      const waiting = page.locator('[data-testid=ticket-group-waiting]')
      await expect(rowOf('waiting', waitId)).toContainText(wait)
      await expect(rowOf('waiting', waitId).locator('[data-testid=ticket-row-mark]')).toHaveText('⏰')
      await expect(rowOf('waiting', waitId).locator('[data-testid=ticket-row-due]')).toHaveText(`Due ${dayFromToday(1)}`)
      await expect(rowOf('waiting', plainId)).toContainText(plain)
      await expect(rowOf('waiting', plainId).locator('[data-testid=ticket-row-mark]')).toHaveCount(0)
      await expect(rowOf('waiting', plainId).locator('[data-testid=ticket-row-due]')).toHaveCount(0)
      await expect(rowOf('attention', overdueId).locator('[data-testid=ticket-row-mark]')).toHaveText('⚠\uFE0F')
      await expect(rowOf('attention', overdueId).locator('[data-testid=ticket-row-due]')).toHaveText(`Due ${dayFromToday(-2)}`)
      await expect(rowOf('running', dueSoonId).locator('[data-testid=ticket-row-mark]')).toHaveText('⏰')
      // Under each title: the first line of what its tab wrote last, as plain text.
      await expect(rowOf('waiting', waitId).locator('[data-testid=ticket-row-next]')).toHaveText('Waiting for the sample deck')
      await expect(rowOf('attention', overdueId).locator('[data-testid=ticket-row-next]')).toHaveText('One line or two?')
      await expect(rowOf('running', dueSoonId).locator('[data-testid=ticket-row-next]')).toHaveText('The title wraps on page 3 <b>of</b> the sample deck.')
      await expect(rowOf('running', dueSoonId).locator('[data-testid=ticket-row-next] b')).toHaveCount(0)
      await page.locator('[data-testid=ticket-group-toggle]').click()
      await expect(rowOf('closed', doneId)).toContainText(done)
      await page.screenshot({ path: testInfo.outputPath('tickets-groups.png') })
      await page.setViewportSize({ width: 390, height: 844 })
      await expect(waiting).toBeVisible()
      await page.screenshot({ path: testInfo.outputPath('tickets-groups-narrow.png') })
    } finally {
      await closeAll(request, made)
    }
  })

  test('the head of the ticket screen has the state and the due date, and no origin for a ticket a tab opened itself', async ({ page, request }, testInfo) => {
    const tab = await seedSession(request, 'e2e-tab-a')
    const id = await openTicket(request, tab.sid, { title: `Head ${Date.now()}`, due: dayFromToday(5) })
    try {
      const open = async () => page.goto(`/?ses=${encodeURIComponent(tab.sid)}&ticket=${encodeURIComponent(id)}`, { waitUntil: 'domcontentloaded' })
      await open()
      await expect(page.locator('[data-testid=ticket-status]')).toHaveText('In progress')
      await expect(page.locator('[data-testid=ticket-due]')).toHaveText(`Due ${dayFromToday(5)}`)
      await expect(page.locator('[data-testid=ticket-origin]')).toHaveCount(0)
      await page.screenshot({ path: testInfo.outputPath('tickets-screen-head.png') })
      await page.setViewportSize({ width: 390, height: 844 })
      await expect(page.locator('[data-testid=ticket-facts]')).toBeVisible()
      await page.screenshot({ path: testInfo.outputPath('tickets-screen-head-narrow.png') })

      await setAside(request, id, tab.sid)
      await open()
      await expect(page.locator('[data-testid=ticket-status]')).toHaveText('Waiting')
    } finally {
      await closeAll(request, [[id, tab.sid]])
    }
  })
})
