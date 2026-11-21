// Golden path: a request one tab keeps as a ticket shows on the operator's screen. The number on the menu button counts the tickets
// that want a look and the first row of the tab list opens the list; the list names each one's request, what it asks, who holds it and how long ago it moved; the ticket
// screen pins the operator's original words and draws the lines as plain text; answering it moves the ticket out of the
// first group; and a ticket handed over reaches the chat as one line that opens the ticket.
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

async function openTicket(request, sender) {
  const opened = await request.post('/tickets', { form: { from: sender, title: TITLE, text: REQUEST } })
  expect(opened.ok()).toBeTruthy()
  const { id } = await opened.json()
  return id
}

async function ask(request, id, sender) {
  const res = await request.post(`/tickets/${id}/asks`, {
    form: { from: sender, kind: 'decide', text: 'One line or two?', recommend: 'One line' },
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
    await expect(page.locator('[data-testid=ticket-question]')).toContainText('One line or two?')
    await expect(page.locator('[data-testid=ticket-recommend]')).toContainText('One line')
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
    await ask(request, id, tab.sid)
    await page.goto(`/?ses=${encodeURIComponent(tab.sid)}&ticket=${encodeURIComponent(id)}`, { waitUntil: 'domcontentloaded' })
    const field = page.locator('[data-testid=ticket-answer-field]')
    await field.fill('Let me think about it')
    await page.locator('[data-testid=ticket-close]').click()
    await openTicketList(page)
    await page.locator(`[data-testid=ticket-row][data-ticket="${id}"]`).click()
    await expect(field).toHaveValue('Let me think about it')
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
})
