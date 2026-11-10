// createScreenFeed: what a terminal socket does with the frames the backend sends it.

import { describe, it, expect } from 'vitest'
import { createScreenFeed } from '../../../src/features/terminal/screenFeed.js'

function setup() {
  const calls = []
  const terminal = {
    reset: () => calls.push(['reset']),
    write: (data) => calls.push(['write', typeof data === 'string' ? data : Array.from(data)]),
  }
  const sent = []
  const exits = []
  const feed = createScreenFeed({
    terminal,
    sendKeys: (keys) => sent.push(keys),
    onExit: (ctrl) => exits.push(ctrl),
  })
  return { feed, calls, sent, exits }
}

const bytes = (...values) => new Uint8Array(values).buffer

describe('createScreenFeed', () => {
  it('resets the terminal right before the first binary frame, then writes it', () => {
    const { feed, calls } = setup()
    feed.handleMessage(bytes(1, 2))
    expect(calls).toEqual([['reset'], ['write', [1, 2]]])
  })

  it('resets only once per socket', () => {
    const { feed, calls } = setup()
    feed.handleMessage(bytes(1))
    feed.handleMessage(bytes(2))
    expect(calls).toEqual([['reset'], ['write', [1]], ['write', [2]]])
  })

  it('does not reset before anything has arrived, so the old screen stays until the new one is ready', () => {
    const { calls } = setup()
    expect(calls).toEqual([])
  })

  it('asks the program for a repaint with Ctrl-L only when the backend has no snapshot', () => {
    const { feed, sent } = setup()
    feed.handleMessage(bytes(1))
    expect(sent).toEqual([])
    feed.handleMessage(JSON.stringify({ type: 'snapshot', status: 'none' }))
    expect(sent).toEqual(['\x0c'])
  })

  it('still resets before the program answers the repaint, so the answer does not stack on the old screen', () => {
    const { feed, calls } = setup()
    feed.handleMessage(JSON.stringify({ type: 'snapshot', status: 'none' }))
    expect(calls).toEqual([])
    feed.handleMessage(bytes(7))
    expect(calls).toEqual([['reset'], ['write', [7]]])
  })

  it('writes an exit notice and reports the exit', () => {
    const { feed, calls, exits } = setup()
    feed.handleMessage(JSON.stringify({ type: 'exit', returncode: 3 }))
    expect(calls).toEqual([['write', '\r\n\x1b[31m[backend reports PTY exited rc=3]\x1b[0m\r\n']])
    expect(exits).toEqual([{ type: 'exit', returncode: 3 }])
  })

  it('writes a backend error notice', () => {
    const { feed, calls } = setup()
    feed.handleMessage(JSON.stringify({ type: 'error', message: 'unknown session' }))
    expect(calls).toEqual([['write', '\r\n\x1b[31m[backend error: unknown session]\x1b[0m\r\n']])
  })

  it('ignores text that is not JSON and control messages it does not know', () => {
    const { feed, calls, sent } = setup()
    feed.handleMessage('not json')
    feed.handleMessage(JSON.stringify({ type: 'pong', ts: 1 }))
    feed.handleMessage(JSON.stringify({ type: 'snapshot', status: 'ok' }))
    expect(calls).toEqual([])
    expect(sent).toEqual([])
  })
})
