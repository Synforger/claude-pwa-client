import { describe, it, expect } from 'vitest'
import { answerLanded, draftState, lowerArea } from '../../../src/features/tickets/ticketLower.js'

const asked = { kind: 'asked', at: '2026-11-19T10:00:00.000+00:00', text: 'A or B?', recommend: 'A' }
const detail = (extra = {}) => ({
  status: 'open', holder: 'ses_a', entries: [{ kind: 'opened', at: '1' }], answer_pending: [], last_delivery: null, ...extra,
})

describe('lowerArea', () => {
  it('has nothing for a ticket that nothing is asked of', () => {
    expect(lowerArea(detail())).toMatchObject({ noHolder: false, asked: null, pending: [], problem: null })
  })

  it('asks for a holder when no tab holds an open ticket, and reads a question without letting it be answered', () => {
    const area = lowerArea(detail({ holder: '', status: 'waiting-operator', entries: [asked] }))
    expect(area.noHolder).toBe(true)
    expect(area.asked).toBeNull()
    expect(area.askedWithoutHolder).toBe(asked)
  })

  it('a closed ticket without a holder asks for none', () => {
    expect(lowerArea(detail({ holder: '', status: 'closed' })).noHolder).toBe(false)
  })

  it('shows the answer box with the recommendation for a question that has one, and without for one that has none', () => {
    const withRecommend = lowerArea(detail({ status: 'waiting-operator', entries: [asked] }))
    expect(withRecommend.asked).toBe(asked)
    expect(withRecommend.hasRecommend).toBe(true)
    const plain = { ...asked, recommend: undefined }
    expect(lowerArea(detail({ status: 'waiting-operator', entries: [plain] })).hasRecommend).toBe(false)
  })

  it('takes the last question when there are several', () => {
    const later = { ...asked, at: '2026-11-19T11:00:00.000+00:00', text: 'C?' }
    expect(lowerArea(detail({ status: 'waiting-operator', entries: [asked, later] })).asked).toBe(later)
  })

  it('says an answer is on its way, for each question it answers, and for a closed ticket', () => {
    const area = lowerArea(detail({ answer_pending: ['t1', 't2'] }))
    expect(area.pending).toEqual(['t1', 't2'])
    expect(area.closedPending).toBe(false)
    expect(lowerArea(detail({ status: 'closed', answer_pending: ['t1'] })).closedPending).toBe(true)
  })

  it('shows a delivery that did not arrive only until something comes after it', () => {
    expect(lowerArea(detail({ last_delivery: { result: 'refused', followed: false } })).problem).toBe('refused')
    expect(lowerArea(detail({ last_delivery: { result: 'unconfirmed', followed: false } })).problem).toBe('unconfirmed')
    expect(lowerArea(detail({ last_delivery: { result: 'refused', followed: true } })).problem).toBeNull()
    expect(lowerArea(detail({ last_delivery: { result: 'typed', followed: false } })).problem).toBeNull()
  })
})

describe('answerLanded', () => {
  it('is true when the last answered line is the answer to the question that was sent', () => {
    const entries = [asked, { kind: 'answered', asked_at: asked.at }]
    expect(answerLanded({ entries }, asked.at)).toBe(true)
    expect(answerLanded({ entries }, 'another')).toBe(false)
    expect(answerLanded({ entries: [asked] }, asked.at)).toBe(false)
  })
})

describe('draftState', () => {
  it('is current for a draft of this question, previous for one of an older question, none for none', () => {
    expect(draftState({ askedAt: 'a', text: 'x' }, 'a')).toBe('current')
    expect(draftState({ askedAt: 'a', text: 'x' }, 'b')).toBe('previous')
    expect(draftState(undefined, 'a')).toBe('none')
    expect(draftState({ askedAt: 'a', text: '' }, 'a')).toBe('none')
  })
})
