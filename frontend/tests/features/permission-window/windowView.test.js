// What the permission window shows for a window: the input in full, the guard's rewrite, the "k / N" position.
import { describe, it, expect } from 'vitest'
import { inputFields, windowView } from '../../../src/features/permission-window/windowView.js'
import { sidsWithWindow } from '../../../src/features/permission-window/windowSids.js'

const LONG_COMMAND = `echo ${'x'.repeat(1500)}\nls -la`

describe('inputFields', () => {
  it('prints a command whole, with its line breaks, and every other key beside it', () => {
    const fields = inputFields({ command: LONG_COMMAND, description: 'list files' })
    expect(fields).toEqual([
      { name: 'command', text: LONG_COMMAND },
      { name: 'description', text: 'list files' },
    ])
    expect(fields[0].text.length).toBe(LONG_COMMAND.length)
  })

  it('prints a value that is not text as indented JSON', () => {
    expect(inputFields({ edits: [{ old: 'a', new: 'b' }], replace_all: false })).toEqual([
      { name: 'edits', text: JSON.stringify([{ old: 'a', new: 'b' }], null, 2) },
      { name: 'replace_all', text: 'false' },
    ])
  })

  it('takes a plain string as one part without a name, and no input as no part', () => {
    expect(inputFields('rm -rf build')).toEqual([{ name: null, text: 'rm -rf build' }])
    expect(inputFields(null)).toEqual([])
    expect(inputFields({})).toEqual([])
  })
})

describe('windowView', () => {
  const base = { number: 3, tool_name: 'Bash', input: { command: 'ls' }, record_input: null, index: 1, count: 1 }

  it('shows the input that runs and nothing to compare it with when the record holds the same', () => {
    const view = windowView(base)
    expect(view.toolName).toBe('Bash')
    expect(view.running).toEqual([{ name: 'command', text: 'ls' }])
    expect(view.original).toBeNull()
  })

  it('also shows the record\'s input when the guard rewrote it', () => {
    const view = windowView({ ...base, input: { command: 'ls -la' }, record_input: { command: 'rm -rf /', description: 'clean' } })
    expect(view.running).toEqual([{ name: 'command', text: 'ls -la' }])
    expect(view.original).toEqual([
      { name: 'command', text: 'rm -rf /' },
      { name: 'description', text: 'clean' },
    ])
  })

  it('gives a position only when two windows or more are queued', () => {
    expect(windowView(base).position).toBeNull()
    expect(windowView({ ...base, index: 2, count: 3 }).position).toEqual({ index: 2, count: 3 })
  })

  it('reads a window that lacks its position as one window', () => {
    const bare = { number: 3, tool_name: 'Bash', input: { command: 'ls' }, record_input: null }
    expect(windowView(bare).position).toBeNull()
  })
})

describe('sidsWithWindow', () => {
  it('lists the tabs whose status carries a window, and no other', () => {
    const status = {
      ses_a: { pending_permission: { number: 1 } },
      ses_b: { pending_permission: null },
      ses_c: { model: 'x' },
      ses_d: null,
    }
    expect([...sidsWithWindow(status)]).toEqual(['ses_a'])
  })

  it('is empty for no snapshot', () => {
    expect(sidsWithWindow(null).size).toBe(0)
    expect(sidsWithWindow(undefined).size).toBe(0)
  })
})
