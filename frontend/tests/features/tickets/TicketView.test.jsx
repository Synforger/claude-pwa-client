// @vitest-environment jsdom
//
// 票の画面: 頭に状態・出どころ・期限、 その下に操作者の原文、 下に件、 一番下の欄は票の今で変わる。 答える・渡す・確かめた の操作と、 下書きの扱い。
import { it, expect, afterEach, beforeEach, vi } from 'vitest'
import { render, cleanup, fireEvent, screen, waitFor, act } from '@testing-library/react'
import TicketView from '../../../src/features/tickets/TicketView.jsx'
import { setOverlay } from '../../../src/state/ui.js'
import { applyTicketsSnapshot, setAnswerDraft } from '../../../src/state/tickets.js'
import * as sessions from '../../../src/state/sessions.js'

const ID = 'home-261119-01'
const ASKED_AT = '2026-11-19T10:00:00.000+00:00'

const line = (kind, at, extra = {}) => ({ kind, at, tab: '', tab_title: '', tier: '', text: '', ...extra })
const detail = (extra = {}) => ({
  ok: true, id: ID, status: 'waiting-operator', wants: 'decide', holder: 'ses_a', opener: 'ses_a', place_outside: true,
  answer_pending: [], last_delivery: null, attention: 'waiting',
  entries: [
    line('opened', '2026-11-19T09:00:00.000+00:00', { tab: 'ses_a', tab_title: 'client work', title: 'Fix the title', text: 'Please fix <b>it</b>' }),
    line('operator', '2026-11-19T09:00:00.001+00:00', { text: 'fix the title please', typed_in: 'ses_a' }),
    line('asked', ASKED_AT, { tab: 'ses_a', tab_title: 'client work', text: 'A or B?', ask_kind: 'decide', recommend: 'A' }),
  ],
  ...extra,
})

let calls
function serve(responses) {
  calls = []
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, init = {}) => {
    const path = String(url).replace(/^https?:\/\/[^/]+/, '')
    calls.push({ path, method: init.method || 'GET', body: init.body ? JSON.parse(init.body) : null })
    const answer = responses(path, init.method || 'GET', calls.length)
    return new Response(JSON.stringify(answer.body), { status: answer.status ?? 200 })
  })
}
const refusal = (status, code) => ({ status, body: { detail: { code, message: code } } })

beforeEach(() => {
  vi.spyOn(sessions, 'getSnapshot').mockReturnValue({
    activeId: 'ses_a', sessions: [{ id: 'ses_a', title: 'client work' }, { id: 'ses_b', title: 'notes' }, { id: 'api_1', title: 'api', kind: 'api' }],
  })
  act(() => { setOverlay('ticket', ID); setAnswerDraft(ID, '', '') })
})

afterEach(() => {
  act(() => { setOverlay('ticket', null); applyTicketsSnapshot({ tickets: [], peers: {} }) })
  cleanup()
  vi.restoreAllMocks()
})

it('pins the operator\'s original words on top and draws the lines as plain text, never as markup', async () => {
  serve(() => ({ body: detail() }))
  render(<TicketView />)
  const original = await screen.findByTestId('ticket-original')
  expect(original.textContent).toContain('fix the title please')
  const entries = screen.getAllByTestId('ticket-entry')
  expect(entries.map((e) => e.dataset.kind)).toEqual(['opened', 'asked'])
  const text = entries[0].textContent
  expect(text).toContain('Please fix <b>it</b>')
  expect(entries[0].querySelector('b')).toBeNull()
})

it('shows the question, the recommendation, and answers with the recommendation', async () => {
  serve((path, method) => (method === 'POST' ? { body: { ok: true, id: ID, queued: true } } : { body: detail() }))
  render(<TicketView />)
  expect((await screen.findByTestId('ticket-question')).textContent).toContain('A or B?')
  expect(screen.getByTestId('ticket-recommend').textContent).toContain('A')
  fireEvent.click(screen.getByTestId('ticket-answer-recommend'))
  await waitFor(() => expect(calls.some((c) => c.method === 'POST')).toBe(true))
  expect(calls.find((c) => c.method === 'POST')).toEqual({
    path: `/tickets/${ID}/answer`, method: 'POST', body: { asked_at: ASKED_AT, recommend: true },
  })
})

it('has no recommendation button for a question without one, and sends the words of the answer field', async () => {
  const plain = detail()
  plain.entries[2] = { ...plain.entries[2], recommend: undefined }
  serve((path, method) => (method === 'POST' ? { body: { ok: true, id: ID, queued: true } } : { body: plain }))
  render(<TicketView />)
  const field = await screen.findByTestId('ticket-answer-field')
  expect(screen.queryByTestId('ticket-answer-recommend')).toBeNull()
  expect(screen.getByTestId('ticket-answer-send').disabled).toBe(true)
  fireEvent.change(field, { target: { value: 'Take B' } })
  fireEvent.click(screen.getByTestId('ticket-answer-send'))
  await waitFor(() => expect(calls.some((c) => c.method === 'POST')).toBe(true))
  expect(calls.find((c) => c.method === 'POST').body).toEqual({ asked_at: ASKED_AT, text: 'Take B' })
})

it('keeps the draft when the ticket is read again', async () => {
  serve(() => ({ body: detail() }))
  render(<TicketView />)
  const field = await screen.findByTestId('ticket-answer-field')
  fireEvent.change(field, { target: { value: 'half written' } })
  act(() => setOverlay('ticket', null))
  act(() => setOverlay('ticket', ID))
  expect((await screen.findByTestId('ticket-answer-field')).value).toBe('half written')
})

it('reads the ticket again when the question changed under the screen, and keeps the draft as a draft for the previous question', async () => {
  const newer = detail()
  newer.entries.push(line('asked', '2026-11-19T10:30:00.000+00:00', { text: 'Or C?', ask_kind: 'decide' }))
  let reads = 0
  serve((path, method) => {
    if (method === 'POST') return refusal(409, 'ticket_ask_changed')
    reads += 1
    return { body: reads === 1 ? detail() : newer }
  })
  render(<TicketView />)
  fireEvent.change(await screen.findByTestId('ticket-answer-field'), { target: { value: 'Take B' } })
  fireEvent.click(screen.getByTestId('ticket-answer-send'))
  const previous = await screen.findByTestId('ticket-draft-previous')
  expect(previous.textContent).toContain('Take B')
  expect(screen.getByTestId('ticket-question').textContent).toContain('Or C?')
  expect(screen.getByTestId('ticket-answer-field').value).toBe('')
})

it('takes an answer that was pressed again as sent when the ticket shows it was already taken', async () => {
  const answered = detail({ status: 'open', attention: null, answer_pending: [ASKED_AT] })
  answered.entries.push(line('answered', '2026-11-19T10:05:00.000+00:00', { text: 'Take B', asked_at: ASKED_AT }))
  let reads = 0
  serve((path, method) => {
    if (method === 'POST') return refusal(409, 'ticket_not_waiting')
    reads += 1
    return { body: reads === 1 ? detail() : answered }
  })
  render(<TicketView />)
  fireEvent.change(await screen.findByTestId('ticket-answer-field'), { target: { value: 'Take B' } })
  fireEvent.click(screen.getByTestId('ticket-answer-send'))
  await screen.findByTestId('ticket-delivering')
  expect(screen.queryByTestId('ticket-error')).toBeNull()
  expect(screen.queryByTestId('ticket-answer-box')).toBeNull()
})

it('shows the refusal when a ticket that does not wait for an answer is pressed and nothing was taken', async () => {
  serve((path, method) => (method === 'POST' ? refusal(409, 'ticket_not_waiting') : { body: detail() }))
  render(<TicketView />)
  fireEvent.change(await screen.findByTestId('ticket-answer-field'), { target: { value: 'x' } })
  fireEvent.click(screen.getByTestId('ticket-answer-send'))
  expect((await screen.findByTestId('ticket-error')).textContent.length).toBeGreaterThan(0)
})

it('says an answer is being delivered, to a closed ticket too', async () => {
  serve(() => ({ body: detail({ status: 'closed', attention: null, answer_pending: [ASKED_AT] }) }))
  render(<TicketView />)
  expect((await screen.findByTestId('ticket-delivering')).textContent).toContain('closed')
})

it('offers a tab to hand a ticket no tab holds to, from the Claude tabs only, and hands it', async () => {
  serve((path, method) => (method === 'POST' ? { body: { ok: true, id: ID, to: 'ses_b' } } : { body: detail({ holder: '' }) }))
  render(<TicketView />)
  const select = await screen.findByTestId('ticket-holder-select')
  expect([...select.options].map((o) => o.value)).toEqual(['', 'ses_a', 'ses_b'])
  expect(screen.getByTestId('ticket-hand-over').disabled).toBe(true)
  fireEvent.change(select, { target: { value: 'ses_b' } })
  fireEvent.click(screen.getByTestId('ticket-hand-over'))
  await waitFor(() => expect(calls.some((c) => c.method === 'POST')).toBe(true))
  expect(calls.find((c) => c.method === 'POST')).toEqual({ path: `/tickets/${ID}/answer/holder`, method: 'POST', body: { to: 'ses_b' } })
})

it('shows a delivery that did not arrive in red and takes the confirmation', async () => {
  serve((path, method) => (method === 'POST' ? { body: { ok: true, id: ID, written: true } }
    : { body: detail({ status: 'open', attention: 'delivery', last_delivery: { result: 'refused', followed: false } }) }))
  render(<TicketView />)
  expect((await screen.findByTestId('ticket-problem')).textContent).toContain('could not be delivered')
  fireEvent.click(screen.getByTestId('ticket-seen'))
  await waitFor(() => expect(calls.some((c) => c.path.endsWith('/answer/seen'))).toBe(true))
})

it('shows what the backend refused with when the ticket is on the other machine', async () => {
  serve(() => refusal(409, 'ticket_elsewhere'))
  render(<TicketView />)
  expect((await screen.findByTestId('ticket-load-error')).textContent.length).toBeGreaterThan(0)
})

const summaryRow = (extra = {}) => ({ id: ID, title: 'Fix the title', status: 'open', holder: 'ses_a', attention: null, origin: 'self', due: null, marks: [], ...extra })

it.each([
  ['open', 'In progress'],
  ['waiting', 'Waiting'],
  ['waiting-operator', 'Waiting for an answer'],
  ['closed', 'Closed'],
])('names the state %s at the head of the screen as "%s"', async (status, shown) => {
  serve(() => ({ body: detail({ status }) }))
  act(() => applyTicketsSnapshot({ tickets: [summaryRow({ status })], peers: {} }))
  render(<TicketView />)
  expect((await screen.findByTestId('ticket-status')).textContent).toBe(shown)
})

it('says the operator asked for it, and the due date, at the head of the screen', async () => {
  serve(() => ({ body: detail() }))
  act(() => applyTicketsSnapshot({ tickets: [summaryRow({ origin: 'operator', due: '2026-11-24' })], peers: {} }))
  render(<TicketView />)
  expect((await screen.findByTestId('ticket-origin')).textContent).toBe("Operator's request")
  expect(screen.getByTestId('ticket-due').textContent).toBe('Due 2026-11-24')
})

it('shows no origin when the ticket was opened by a tab itself, and no due date when there is none', async () => {
  serve(() => ({ body: detail() }))
  act(() => applyTicketsSnapshot({ tickets: [summaryRow()], peers: {} }))
  render(<TicketView />)
  await screen.findByTestId('ticket-status')
  expect(screen.queryByTestId('ticket-origin')).toBeNull()
  expect(screen.queryByTestId('ticket-due')).toBeNull()
})

it('draws the head from a row of an older backend that has none of the new fields', async () => {
  serve(() => ({ body: detail() }))
  const old = summaryRow()
  for (const field of ['origin', 'due', 'marks']) delete old[field]
  act(() => applyTicketsSnapshot({ tickets: [old], peers: {} }))
  render(<TicketView />)
  expect((await screen.findByTestId('ticket-status')).textContent).toBe('In progress')
  expect(screen.queryByTestId('ticket-origin')).toBeNull()
})
