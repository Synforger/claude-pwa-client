import { describe, it, expect } from 'vitest'
import {
  CLOSED_SHOWN_DAYS, GROUPS, agoOf, attentionCount, attentionCounts, factsOf, groupTickets, holderOf, markOf, peerLines, ticketLabel, ticketSections,
} from '../../../src/features/tickets/ticketGroups.js'

const ticket = (id, extra = {}) => ({ id, title: `T ${id}`, status: 'open', holder: 'ses_a', attention: null, last_at: '2026-11-19T10:00:00.000+00:00', ...extra })

const NOW = Date.parse('2026-11-19T12:00:00.000Z')

describe('groupTickets', () => {
  it('puts a ticket that wants a look first, whatever its state, and keeps the closed ones apart', () => {
    const groups = groupTickets([
      ticket('a'),
      ticket('b', { status: 'waiting-operator', attention: 'waiting' }),
      ticket('c', { status: 'closed' }),
      ticket('d', { status: 'closed', attention: 'delivery' }),
    ], NOW)
    expect(groups.attention.map((t) => t.id)).toEqual(['b', 'd'])
    expect(groups.running.map((t) => t.id)).toEqual(['a'])
    expect(groups.closed.map((t) => t.id)).toEqual(['c'])
  })

  it('has the four groups in the order the list shows them', () => {
    expect(GROUPS).toEqual(['attention', 'running', 'waiting', 'closed'])
    expect(Object.keys(groupTickets([], NOW))).toEqual(GROUPS)
  })

  it('puts a waiting ticket in its own group, and keeps a waiting ticket that wants a look in the first group', () => {
    const groups = groupTickets([
      ticket('run'),
      ticket('wait', { status: 'waiting' }),
      ticket('lost-holder', { status: 'waiting', holder: '', attention: 'no_holder' }),
      ticket('asked', { status: 'waiting-operator', attention: 'waiting' }),
    ], NOW)
    expect(groups.waiting.map((t) => t.id)).toEqual(['wait'])
    expect(groups.running.map((t) => t.id)).toEqual(['run'])
    expect(groups.attention.map((t) => t.id)).toEqual(['asked', 'lost-holder'])
  })

  it('sorts the waiting group the newest first, like the others', () => {
    const groups = groupTickets([
      ticket('old', { status: 'waiting', last_at: '2026-11-19T08:00:00.000+00:00' }),
      ticket('new', { status: 'waiting', last_at: '2026-11-19T11:00:00.000+00:00' }),
    ], NOW)
    expect(groups.waiting.map((t) => t.id)).toEqual(['new', 'old'])
  })

  it('puts the ones that wait for the answer before the ones whose answer did not arrive, then the newest first', () => {
    const groups = groupTickets([
      ticket('old-wait', { attention: 'waiting', last_at: '2026-11-19T08:00:00.000+00:00' }),
      ticket('lost', { attention: 'delivery', last_at: '2026-11-19T12:00:00.000+00:00' }),
      ticket('new-wait', { attention: 'waiting', last_at: '2026-11-19T11:00:00.000+00:00' }),
    ], NOW)
    expect(groups.attention.map((t) => t.id)).toEqual(['new-wait', 'old-wait', 'lost'])
  })

  describe('the closed tickets shown', () => {
    const sevenDaysAgo = NOW - CLOSED_SHOWN_DAYS * 24 * 60 * 60 * 1000
    const closedAt = (id, ms, extra = {}) => ticket(id, { status: 'closed', last_at: new Date(ms).toISOString(), ...extra })

    it('keeps the ones whose last entry is within 7 days, up to the boundary, and leaves out the older ones', () => {
      const groups = groupTickets([
        closedAt('just-inside', sevenDaysAgo + 1),
        closedAt('on-the-line', sevenDaysAgo),
        closedAt('just-outside', sevenDaysAgo - 1),
        closedAt('long-ago', NOW - 90 * 24 * 60 * 60 * 1000),
      ], NOW)
      expect(groups.closed.map((t) => t.id)).toEqual(['just-inside', 'on-the-line'])
    })

    it('judges a ticket with no last entry by the time it was opened', () => {
      const groups = groupTickets([
        ticket('opened-lately', { status: 'closed', last_at: null, opened_at: new Date(NOW - 60_000).toISOString() }),
        ticket('opened-long-ago', { status: 'closed', last_at: '', opened_at: new Date(sevenDaysAgo - 1).toISOString() }),
      ], NOW)
      expect(groups.closed.map((t) => t.id)).toEqual(['opened-lately'])
    })

    it('leaves out a closed ticket whose time cannot be read, and does not touch the others', () => {
      const groups = groupTickets([
        ticket('no-time', { status: 'closed', last_at: null, opened_at: null }),
        ticket('open-old', { last_at: '2020-01-01T00:00:00.000+00:00' }),
        ticket('wants-a-look', { status: 'closed', attention: 'delivery', last_at: '2020-01-01T00:00:00.000+00:00' }),
      ], NOW)
      expect(groups.closed).toEqual([])
      expect(groups.running.map((t) => t.id)).toEqual(['open-old'])
      expect(groups.attention.map((t) => t.id)).toEqual(['wants-a-look'])
    })
  })

  it('counts the tickets that want a look', () => {
    expect(attentionCount([ticket('a'), ticket('b', { attention: 'no_holder' }), ticket('c', { attention: 'waiting' })])).toBe(2)
    expect(attentionCount([])).toBe(0)
  })
})

describe('agoOf', () => {
  const now = Date.parse('2026-11-19T12:00:00.000Z')
  it.each([
    ['2026-11-19T11:59:40.000Z', { unit: 'now', count: 0 }],
    ['2026-11-19T11:15:00.000Z', { unit: 'minutes', count: 45 }],
    ['2026-11-19T07:00:00.000Z', { unit: 'hours', count: 5 }],
    ['2026-11-16T12:00:00.000Z', { unit: 'days', count: 3 }],
  ])('%s', (iso, expected) => { expect(agoOf(iso, now)).toEqual(expected) })

  it('gives nothing for a time it cannot read', () => {
    expect(agoOf('', now)).toBeNull()
    expect(agoOf('soon', now)).toBeNull()
  })
})

describe('markOf', () => {
  it.each([
    [['overdue'], 'overdue', '⚠\uFE0F'],
    [['due_soon'], 'due_soon', '⏰'],
    [['waiting_stale'], 'waiting_stale', '💤'],
    [['idle'], 'idle', '💤'],
  ])('%j is one character', (marks, key, glyph) => {
    expect(markOf({ marks })).toEqual({ key, glyph })
  })

  it('takes the first of the marks, which come in the order of priority', () => {
    expect(markOf({ marks: ['overdue', 'idle'] })).toEqual({ key: 'overdue', glyph: '⚠\uFE0F' })
    expect(markOf({ marks: ['due_soon', 'waiting_stale'] })).toEqual({ key: 'due_soon', glyph: '⏰' })
  })

  it('skips a mark this screen does not know, and gives nothing for no marks or a row without the field', () => {
    expect(markOf({ marks: ['from_the_future', 'idle'] })).toEqual({ key: 'idle', glyph: '💤' })
    expect(markOf({ marks: ['from_the_future'] })).toBeNull()
    expect(markOf({ marks: [] })).toBeNull()
    expect(markOf({})).toBeNull()
    expect(markOf({ marks: null })).toBeNull()
  })
})

describe('factsOf', () => {
  it('names the state with the key the i18n uses, for every state', () => {
    expect(['open', 'waiting', 'waiting-operator', 'closed'].map((status) => factsOf({ status }).status))
      .toEqual(['open', 'waiting', 'waiting_operator', 'closed'])
  })

  it('says the operator asked for it only when the origin is the operator', () => {
    expect(factsOf({ status: 'open', origin: 'operator' }).fromOperator).toBe(true)
    expect(factsOf({ status: 'open', origin: 'self' }).fromOperator).toBe(false)
    expect(factsOf({ status: 'open' }).fromOperator).toBe(false)
  })

  it('gives the due date, or null when there is none or the row has no such field', () => {
    expect(factsOf({ status: 'open', due: '2026-11-24' }).due).toBe('2026-11-24')
    expect(factsOf({ status: 'open', due: null }).due).toBeNull()
    expect(factsOf({ status: 'open' }).due).toBeNull()
  })
})

describe('holderOf and ticketLabel', () => {
  it('tells no holder, a tab of the other machine and a tab of this one apart', () => {
    expect(holderOf('')).toEqual({ kind: 'none' })
    expect(holderOf('company:ses_x')).toEqual({ kind: 'machine', machine: 'company' })
    expect(holderOf('ses_a')).toEqual({ kind: 'tab', id: 'ses_a' })
  })

  it('names a ticket by its title, or by its id when the title cannot be read', () => {
    expect(ticketLabel({ id: 'x', title: 'Fix it' })).toBe('Fix it')
    expect(ticketLabel({ id: 'x', title: null })).toBe('x')
  })
})

describe('ticketSections and attentionCounts', () => {
  const now = Date.parse('2026-11-22T10:00:00Z')
  const t = (id, holder, extra = {}) => ({ id, title: id, status: 'open', holder, attention: null, marks: [], last_at: '2026-11-22T09:00:00Z', ...extra })
  const all = [t('mine', 'ses_a'), t('quiet', 'ses_b'), t('asks', 'ses_c', { attention: 'waiting' }), t('done', 'ses_a', { status: 'closed' })]
  it('gives each ticket once: this tab, the other holders with the ones to look at first, the closed', () => {
    const { own, others, closed } = ticketSections(all, 'ses_a', now)
    expect(own.running.map((x) => x.id)).toEqual(['mine'])
    expect(others.map((x) => x.holder)).toEqual(['ses_c', 'ses_b'])
    expect(closed.map((x) => x.id)).toEqual(['done'])
  })
  it('has no own section without a tab, and loses no ticket', () => {
    const { own, others } = ticketSections(all, null, now)
    expect(own).toBeNull()
    expect(others).toHaveLength(3)
  })
  it('counts only what the operator acts on, for this tab and for all', () => {
    expect(attentionCounts(all, 'ses_a')).toEqual({ own: 0, total: 1 })
    expect(attentionCounts(all, 'ses_c')).toEqual({ own: 1, total: 1 })
  })
})

describe('peerLines', () => {
  it('gives each other machine\'s waiting count, or null when it cannot be read', () => {
    expect(peerLines({ company: { waiting: 2 }, away: { unreadable: true } })).toEqual([
      { machine: 'away', waiting: null }, { machine: 'company', waiting: 2 },
    ])
    expect(peerLines({})).toEqual([])
  })

  it('leaves out a machine with no ticket waiting, but not one that cannot be read', () => {
    expect(peerLines({ company: { waiting: 0 }, home: {}, away: { unreadable: true }, far: { waiting: 1 } })).toEqual([
      { machine: 'away', waiting: null }, { machine: 'far', waiting: 1 },
    ])
  })
})


describe('needsOperator and attentionCount', () => {
  const t = (id, extra = {}) => ({ id, status: 'open', holder: 'ses_a', attention: null, marks: [], ...extra })
  it('counts what the operator acts on: an answer awaited, no holder, a delivery problem, a due day past', () => {
    expect(attentionCount([
      t('a', { attention: 'waiting', status: 'waiting-operator' }), t('b', { attention: 'no_holder', holder: '' }),
      t('c', { attention: 'delivery' }), t('d', { marks: ['overdue'] }),
    ])).toBe(4)
  })
  it('leaves out the tickets tabs pass between them, moving or waiting, also when due soon or quiet', () => {
    expect(attentionCount([t('a'), t('b', { status: 'waiting' }), t('c', { marks: ['due_soon'] }), t('d', { marks: ['idle'] })])).toBe(0)
  })
  it('puts an overdue ticket in the first group', () => {
    expect(groupTickets([t('d', { marks: ['overdue'] })], Date.parse('2026-11-21T00:00:00Z')).attention.map((x) => x.id)).toEqual(['d'])
  })
})
