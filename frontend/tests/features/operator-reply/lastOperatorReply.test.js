// The last answer given to the operator, chosen from the order of a conversation.
import { describe, it, expect } from 'vitest'
import { lastOperatorReply, replyKeyOf, startsOperatorTurn } from '../../../src/features/operator-reply/lastOperatorReply.js'
import {
  AGENT_MESSAGE_OPENING, CLIENT_NOTICE_OPENING, ROLLOVER_OPENING, TAB_OPEN_OPENING,
} from '../../../src/features/chat/agentMessage.js'

// Rows without a time; `convo` stamps them in the order given (one second apart), so a test reads top to bottom.
const operator = (uuid, text = 'a question') => ({ role: 'user', uuid, text })
const agent = (uuid, text, extra = {}) => ({ role: 'agent', uuid, text, tools: [], ...extra })
const relayed = (uuid) => ({
  role: 'user', uuid,
  text: `${AGENT_MESSAGE_OPENING}\n<agent-message from="Desk" session="ses_x">\nplease look\n</agent-message>`,
})
const notice = (uuid) => ({
  role: 'user', uuid,
  text: `${CLIENT_NOTICE_OPENING}\n<limit-resume account="main">\nback\n</limit-resume>`,
})
const rollover = (uuid, phase) => ({
  role: 'user', uuid,
  text: `${ROLLOVER_OPENING}\n<session-rollover phase="${phase}">\nbody\n</session-rollover>`,
})
const tabOpen = (uuid) => ({
  role: 'user', uuid,
  text: `${TAB_OPEN_OPENING}\n<tab-open>\ntier=normal\n</tab-open>`,
})
const convo = (...rows) => rows.map((row, i) => ({ ...row, ts: (i + 1) * 1000 }))

describe('which user rows start a turn for the operator', () => {
  it('counts what the operator typed and the start of an automatic rollover', () => {
    expect(startsOperatorTurn(operator('u1'))).toBe(true)
    expect(startsOperatorTurn(rollover('u2', 'start'))).toBe(true)
  })

  it('leaves out a relayed note, a client notice, the close of a rollover and the first row of a tier tab', () => {
    expect(startsOperatorTurn(relayed('u1'))).toBe(false)
    expect(startsOperatorTurn(notice('u2'))).toBe(false)
    expect(startsOperatorTurn(rollover('u3', 'close'))).toBe(false)
    expect(startsOperatorTurn(tabOpen('u4'))).toBe(false)
    expect(startsOperatorTurn(agent('a1', 'text'))).toBe(false)
  })
})

describe('lastOperatorReply', () => {
  it('gives nothing for an empty conversation or one without an answer to the operator', () => {
    expect(lastOperatorReply(undefined)).toBeNull()
    expect(lastOperatorReply([])).toBeNull()
    expect(lastOperatorReply(convo(operator('u1')))).toBeNull()
    expect(lastOperatorReply(convo(relayed('u1'), agent('a1', 'a reply to a note')))).toBeNull()
  })

  it('chooses the first agent text when a relayed note and a notice follow (the reply to the note is not an answer)', () => {
    const found = lastOperatorReply(convo(
      operator('u1', 'what should we do?'),
      agent('a1', 'the recommendation'),
      relayed('u2'),
      agent('a2', 'reply to the note'),
      notice('u3'),
    ))
    expect(found.reply.uuid).toBe('a1')
    expect(found.prompt.text).toBe('what should we do?')
    expect(found.ongoing).toBe(false)
  })

  it('chooses the last agent text of the turn, skipping rows that only call tools', () => {
    const found = lastOperatorReply(convo(
      operator('u1'),
      agent('a1', 'I will look first'),
      agent('a1b', '', { tools: [{ id: 't1', name: 'Read' }] }),
      agent('a2', 'the final answer'),
      agent('a3', '   ', { tools: [{ id: 't2', name: 'Bash' }] }),
    ))
    expect(found.reply.uuid).toBe('a2')
  })

  it('takes the report that begins an automatic rollover, and not the close', () => {
    const found = lastOperatorReply(convo(
      operator('u1'), agent('a1', 'an older answer'),
      rollover('u2', 'close'), agent('a-close', 'handover written'),
      rollover('u3', 'start'), agent('a2', 'good morning, here is where we are'),
    ))
    expect(found.reply.uuid).toBe('a2')
    expect(found.prompt.text).toContain('phase="start"')
    // the operator's last answer before the rollover is kept too, so the new session need not write it again
    expect(found.before.reply.uuid).toBe('a1')
    expect(found.before.prompt.uuid).toBe('u1')
  })

  it('has nothing before when the last answer is to the operator\'s own words', () => {
    const found = lastOperatorReply(convo(
      rollover('u1', 'start'), agent('a1', 'briefing'),
      operator('u2'), agent('a2', 'the answer'),
    ))
    expect(found.reply.uuid).toBe('a2')
    expect(found.before).toBeNull()
  })

  it('keeps the answer before the last of several rollovers', () => {
    const found = lastOperatorReply(convo(
      operator('u1'), agent('a1', 'the operator answer'),
      rollover('u2', 'start'), agent('a2', 'first briefing'),
      rollover('u3', 'start'), agent('a3', 'second briefing'),
    ))
    expect(found.reply.uuid).toBe('a3')
    expect(found.before.reply.uuid).toBe('a1')
  })

  it('does not start an answer from the first row of a tier tab', () => {
    const found = lastOperatorReply(convo(operator('u1'), agent('a1', 'an answer'), tabOpen('u2'), agent('a2', 'tab startup output')))
    expect(found.reply.uuid).toBe('a1')
  })

  it('keeps the earlier answer while the new turn has no text yet', () => {
    const found = lastOperatorReply(convo(
      operator('u1'), agent('a1', 'the earlier answer'),
      operator('u2', 'a new question'), agent('a2', '', { tools: [{ id: 't1', name: 'Read' }], streaming: true }),
    ))
    expect(found.reply.uuid).toBe('a1')
    expect(found.ongoing).toBe(false)
  })

  it('says the turn is still going while the last row is being written, and shows the text so far', () => {
    const found = lastOperatorReply(convo(operator('u1'), agent('a1', 'half a sent', { streaming: true })))
    expect(found.reply.text).toBe('half a sent')
    expect(found.ongoing).toBe(true)
  })

  it('still counts the turn as going when the row being written only calls a tool', () => {
    const found = lastOperatorReply(convo(
      operator('u1'), agent('a1', 'I will check'),
      agent('a2', '', { tools: [{ id: 't1', name: 'Bash' }], streaming: true }),
    ))
    expect(found.reply.uuid).toBe('a1')
    expect(found.ongoing).toBe(true)
  })

  it('does not call a finished turn going because an older row kept its flag, nor a turn a note came after', () => {
    expect(lastOperatorReply(convo(operator('u1'), agent('a1', 'intermediate', { streaming: true }), agent('a2', 'final'))).ongoing).toBe(false)
    const afterNote = lastOperatorReply(convo(
      operator('u1'), agent('a3', 'answer', { streaming: true }), relayed('u2'), agent('a4', 'reply', { streaming: true }),
    ))
    expect(afterNote.reply.uuid).toBe('a3')
    expect(afterNote.ongoing).toBe(false)
  })

  it('orders by time, not by position', () => {
    const found = lastOperatorReply([
      { ...agent('a1', 'answer'), ts: 9_000_000 },
      { ...operator('u1'), ts: 8_000_000 },
    ])
    expect(found.reply.uuid).toBe('a1')
  })

  it('ignores system rows', () => {
    const found = lastOperatorReply(convo(operator('u1'), agent('a1', 'answer'), { role: 'system', uuid: null, kind: 'compact' }))
    expect(found.reply.uuid).toBe('a1')
    expect(found.ongoing).toBe(false)
  })
})

describe('replyKeyOf', () => {
  it('is the row id, else its uuid, else null', () => {
    expect(replyKeyOf({ id: 'x', uuid: 'y' })).toBe('x')
    expect(replyKeyOf({ uuid: 'y' })).toBe('y')
    expect(replyKeyOf(null)).toBeNull()
  })
})
