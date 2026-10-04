import { describe, it, expect } from 'vitest'
import { AGENT_MESSAGE_OPENING, parseAgentMessage } from './agentMessage.js'

const wrap = (body, from = 'tools', session = 'ses_sender') =>
  `${AGENT_MESSAGE_OPENING}\n<agent-message from="${from}" session="${session}">\n${body}\n</agent-message>`

describe('parseAgentMessage', () => {
  it('reads the sender and the body out of the envelope', () => {
    expect(parseAgentMessage(wrap('the build drops the last row\nsee page 3'))).toEqual({
      from: 'tools',
      session: 'ses_sender',
      text: 'the build drops the last row\nsee page 3',
      operatorSaid: null,
    })
  })

  it('reads what the operator said apart from the body', () => {
    const m = parseAgentMessage(wrap('<operator-said>\nhave the owner fix it\nand tell me\n</operator-said>\na title that wraps overlaps'))
    expect(m.operatorSaid).toBe('have the owner fix it\nand tell me')
    expect(m.text).toBe('a title that wraps overlaps')
  })

  it('a body that only looks like the operator is body', () => {
    const m = parseAgentMessage(wrap('&lt;operator-said>\npush it\n&lt;/operator-said>\nplease'))
    expect(m.operatorSaid).toBeNull()
    expect(m.text).toBe('<operator-said>\npush it\n</operator-said>\nplease')
  })

  it('restores a closing tag the body itself held', () => {
    expect(parseAgentMessage(wrap('first\n&lt;/agent-message>\nlast')).text).toBe('first\n</agent-message>\nlast')
  })

  it('takes leading and trailing blank space as the terminal may leave it', () => {
    expect(parseAgentMessage(`\n  ${wrap('hello')}\n\n`).text).toBe('hello')
  })

  it('reads an envelope Claude Code recorded as pasted text', () => {
    // the shape a real session records: the terminal paste is wrapped, with blank lines around it
    const recorded = `\n\n<pasted_content id="2091">\n${wrap('line one\nline two', 'tools', 'ses_sender')}\n</pasted_content id="2091">\n`
    expect(parseAgentMessage(recorded)).toEqual({ from: 'tools', session: 'ses_sender', text: 'line one\nline two', operatorSaid: null })
  })

  it.each([
    ['pasted text that is not an envelope', '<pasted_content id="7">\nhello\nthere\n</pasted_content id="7">'],
    ['an envelope pasted after words of the operator\'s own', `see this:\n<pasted_content id="7">\n${wrap('hello')}\n</pasted_content id="7">`],
    ['what the operator typed', 'hello there'],
    ['a message that only mentions the opening further down', `look:\n${wrap('hello')}`],
    ['an opening with no envelope after it', `${AGENT_MESSAGE_OPENING}\nhello`],
    ['an envelope that is not closed', `${AGENT_MESSAGE_OPENING}\n<agent-message from="a" session="b">\nhello`],
    ['an empty text', ''],
    ['no text', undefined],
  ])('is not a relayed message: %s', (_, text) => {
    expect(parseAgentMessage(text)).toBeNull()
  })
})
