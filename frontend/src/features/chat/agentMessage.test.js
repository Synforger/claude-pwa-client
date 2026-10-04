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
    })
  })

  it('restores a closing tag the body itself held', () => {
    expect(parseAgentMessage(wrap('first\n&lt;/agent-message>\nlast')).text).toBe('first\n</agent-message>\nlast')
  })

  it('takes leading and trailing blank space as the terminal may leave it', () => {
    expect(parseAgentMessage(`\n  ${wrap('hello')}\n\n`).text).toBe('hello')
  })

  it.each([
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
