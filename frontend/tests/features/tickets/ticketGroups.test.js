import { describe, it, expect } from 'vitest'
import {
  agoOf, attentionCount, groupTickets, heldByTab, holderOf, peerLines, ticketLabel,
} from '../../../src/features/tickets/ticketGroups.js'

const ticket = (id, extra = {}) => ({ id, title: `T ${id}`, status: 'open', holder: 'ses_a', attention: null, last_at: '2026-11-19T10:00:00.000+00:00', ...extra })

describe('groupTickets', () => {
  it('puts a ticket that wants a look first, whatever its state, and keeps the closed ones apart', () => {
    const groups = groupTickets([
      ticket('a'),
      ticket('b', { status: 'waiting-operator', attention: 'waiting' }),
      ticket('c', { status: 'closed' }),
      ticket('d', { status: 'closed', attention: 'delivery' }),
    ])
    expect(groups.attention.map((t) => t.id)).toEqual(['b', 'd'])
    expect(groups.running.map((t) => t.id)).toEqual(['a'])
    expect(groups.closed.map((t) => t.id)).toEqual(['c'])
  })

  it('puts the ones that wait for the answer before the ones whose answer did not arrive, then the newest first', () => {
    const groups = groupTickets([
      ticket('old-wait', { attention: 'waiting', last_at: '2026-11-19T08:00:00.000+00:00' }),
      ticket('lost', { attention: 'delivery', last_at: '2026-11-19T12:00:00.000+00:00' }),
      ticket('new-wait', { attention: 'waiting', last_at: '2026-11-19T11:00:00.000+00:00' }),
    ])
    expect(groups.attention.map((t) => t.id)).toEqual(['new-wait', 'old-wait', 'lost'])
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

describe('holderOf and heldByTab', () => {
  it('tells no holder, a tab of the other machine and a tab of this one apart', () => {
    expect(holderOf('')).toEqual({ kind: 'none' })
    expect(holderOf('company:ses_x')).toEqual({ kind: 'machine', machine: 'company' })
    expect(holderOf('ses_a')).toEqual({ kind: 'tab', id: 'ses_a' })
  })

  it('lists the open tickets a tab of this machine holds, by title, and not the closed or the other machine\'s', () => {
    const held = heldByTab([
      ticket('a', { holder: 'ses_a' }),
      ticket('b', { holder: 'ses_a', title: null }),
      ticket('c', { holder: 'ses_a', status: 'closed' }),
      ticket('d', { holder: 'company:ses_a' }),
      ticket('e', { holder: '' }),
    ])
    expect(held).toEqual({ ses_a: [{ id: 'a', label: 'T a' }, { id: 'b', label: 'b' }] })
  })

  it('names a ticket by its title, or by its id when the title cannot be read', () => {
    expect(ticketLabel({ id: 'x', title: 'Fix it' })).toBe('Fix it')
    expect(ticketLabel({ id: 'x', title: null })).toBe('x')
  })
})

describe('peerLines', () => {
  it('gives each other machine\'s waiting count, or null when it cannot be read', () => {
    expect(peerLines({ company: { waiting: 2 }, away: { unreadable: true } })).toEqual([
      { machine: 'away', waiting: null }, { machine: 'company', waiting: 2 },
    ])
    expect(peerLines({})).toEqual([])
  })
})
