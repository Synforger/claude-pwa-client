// @vitest-environment jsdom
//
// 票の画面は、 チャットと同じ「最新の所で開き、 届いたら付いていき、 上へ送って読んでいる間は引き戻さない」 形。
// jsdom には layout が無いので、 送る容器 (= .ticket-body) の高さと位置は試験の中で持つ。
import { it, expect, afterEach, beforeEach, vi } from 'vitest'
import { render, cleanup, fireEvent, screen, waitFor, act } from '@testing-library/react'
import TicketView from '../../../src/features/tickets/TicketView.jsx'
import { setOverlay } from '../../../src/state/ui.js'
import { applyTicketsSnapshot } from '../../../src/state/tickets.js'
import { AT_BOTTOM_THRESHOLD_PX } from '../../../src/features/chat/stickToBottom.js'
import * as sessions from '../../../src/state/sessions.js'

const ID = 'home-261122-11'
const VIEW_HEIGHT = 500
const ENTRY_HEIGHT = 100

const line = (kind, at, extra = {}) => ({ kind, at, tab: 'ses_a', tab_title: 'client work', tier: '', text: '', ...extra })
const entriesOf = (count) => [
  line('opened', '2026-11-22T09:00:00.000+00:00', { title: 'A long ticket', text: 'The request' }),
  ...Array.from({ length: count }, (_, index) => line('added', `2026-11-22T10:${String(index).padStart(2, '0')}:00.000+00:00`, { text: `Line ${index + 1}` })),
]
const detailOf = (count) => ({
  ok: true, id: ID, status: 'open', wants: null, holder: 'ses_a', opener: 'ses_a', place_outside: true,
  answer_pending: [], last_delivery: null, attention: null, entries: entriesOf(count),
})
const summaryOf = (lastAt) => ({ id: ID, title: 'A long ticket', status: 'open', holder: 'ses_a', attention: null, origin: 'self', due: null, marks: [], last_at: lastAt })

// jsdom has no layout: the scroll box's content is as tall as its entries are many, and its position is kept here.
let entryCount
let tops
const isBox = (el) => el.classList?.contains('ticket-body')

function installBox() {
  tops = new WeakMap()
  vi.spyOn(HTMLElement.prototype, 'scrollHeight', 'get').mockImplementation(function scrollHeight() { return isBox(this) ? entryCount * ENTRY_HEIGHT : 0 })
  vi.spyOn(HTMLElement.prototype, 'clientHeight', 'get').mockImplementation(function clientHeight() { return isBox(this) ? VIEW_HEIGHT : 0 })
  vi.spyOn(HTMLElement.prototype, 'scrollTop', 'get').mockImplementation(function scrollTop() { return tops.get(this) ?? 0 })
  vi.spyOn(HTMLElement.prototype, 'scrollTop', 'set').mockImplementation(function scrollTop(value) { tops.set(this, value) })
}

// the ticket as the backend answers it now
let served
function serve() {
  vi.spyOn(globalThis, 'fetch').mockImplementation(async () => new Response(JSON.stringify(detailOf(served)), { status: 200 }))
}
const box = () => screen.getByTestId('ticket-view').querySelector('.ticket-body')
const bottomOf = () => entryCount * ENTRY_HEIGHT

// a new line arrives: the backend now has one more, and the row in the list moves (= what tells the screen to read again)
async function arrive() {
  served += 1
  entryCount = served + 1
  act(() => applyTicketsSnapshot({ tickets: [summaryOf(`2026-11-22T11:${String(served).padStart(2, '0')}:00.000+00:00`)], peers: {} }))
  await screen.findByText(`Line ${served}`)
}

beforeEach(() => {
  served = 20
  entryCount = served + 1
  installBox()
  serve()
  vi.spyOn(sessions, 'getSnapshot').mockReturnValue({ activeId: 'ses_a', sessions: [{ id: 'ses_a', title: 'client work' }] })
  act(() => applyTicketsSnapshot({ tickets: [summaryOf('2026-11-22T10:19:00.000+00:00')], peers: {} }))
  act(() => setOverlay('ticket', ID))
})

afterEach(() => {
  act(() => { setOverlay('ticket', null); applyTicketsSnapshot({ tickets: [], peers: {} }) })
  cleanup()
  vi.restoreAllMocks()
})

it('opens on the newest line, not on the top', async () => {
  render(<TicketView />)
  await screen.findByText('Line 20')
  expect(box().scrollTop).toBe(bottomOf())
})

it('follows a line that arrives while the ticket is open and the screen is at the bottom', async () => {
  render(<TicketView />)
  await screen.findByText('Line 20')
  await arrive()
  await waitFor(() => expect(box().scrollTop).toBe(bottomOf()))
})

it('does not pull the screen back down while the operator has scrolled up to read the past', async () => {
  render(<TicketView />)
  await screen.findByText('Line 20')
  act(() => { tops.set(box(), 300); fireEvent.scroll(box()) })
  await arrive()
  await screen.findByText('Line 21')
  expect(box().scrollTop).toBe(300)
})

it('follows again once the operator has scrolled back down to the bottom', async () => {
  render(<TicketView />)
  await screen.findByText('Line 20')
  act(() => { tops.set(box(), 300); fireEvent.scroll(box()) })
  act(() => { tops.set(box(), bottomOf() - VIEW_HEIGHT - AT_BOTTOM_THRESHOLD_PX); fireEvent.scroll(box()) })
  await arrive()
  await waitFor(() => expect(box().scrollTop).toBe(bottomOf()))
})
