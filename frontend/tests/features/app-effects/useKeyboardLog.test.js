// @vitest-environment jsdom
//
// The keyboard log writes one `keyboard:focus` line when a field that takes text gets the focus and one
// `keyboard:composition` line when it leaves, so the record shows which field held the keyboard and whether a
// Japanese conversion started in it. It never keeps what is typed, and a field tapped again and again is thinned out.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { watchKeyboard, describeField } from '../../../src/features/app-effects/useKeyboardLog.js'

let send
let clock
let stop

function start() {
  clock = 1_000
  send = vi.fn()
  stop = watchKeyboard({ doc: document, win: window, send, now: () => clock })
}

function compose(field) {
  field.dispatchEvent(new CompositionEvent('compositionstart', { bubbles: true }))
}

function stages() {
  return send.mock.calls.map(([line]) => line.stage)
}

beforeEach(() => {
  document.body.innerHTML = `
    <textarea data-testid="chat-input" rows="2"></textarea>
    <input data-testid="terminal-input" autocorrect="off" autocomplete="off" spellcheck="false"
           autocapitalize="off" enterkeyhint="send" type="text" />
    <textarea class="xterm-helper-textarea extra" readonly inputmode="none"></textarea>
    <div contenteditable="true" id="editable"></div>
    <button id="button">Send</button>
    <input type="checkbox" id="check" />
  `
  start()
})

afterEach(() => {
  stop()
  document.body.innerHTML = ''
  vi.restoreAllMocks()
})

describe('watchKeyboard', () => {
  it('writes a focus line with the field, its attributes and the container, then a composition line on blur', () => {
    const field = document.querySelector('[data-testid=terminal-input]')
    field.focus()
    clock += 4_000
    field.blur()

    expect(stages()).toEqual(['keyboard:focus', 'keyboard:composition'])
    const [focus, composition] = send.mock.calls.map(([line]) => line)
    expect(focus).toMatchObject({
      tag: 'input',
      name: 'terminal-input',
      attributes: {
        autocorrect: 'off', autocomplete: 'off', spellcheck: 'false', autocapitalize: 'off',
        enterkeyhint: 'send', type: 'text', inputmode: null,
      },
      readonly: false,
      container: 'browser',
    })
    expect(focus).toHaveProperty('hasOffsetParent')
    expect(focus).toHaveProperty('width')
    expect(focus).toHaveProperty('height')
    expect(focus).toHaveProperty('vvHeight')
    expect(composition).toMatchObject({ name: 'terminal-input', compositions: 0, firstAfterSec: null, focusSec: 4 })
  })

  it('counts the conversions that start while a field holds the focus, and when the first one did', () => {
    const field = document.querySelector('[data-testid=chat-input]')
    field.focus()
    clock += 2_500
    compose(field)
    clock += 1_000
    compose(field)
    clock += 1_500
    field.blur()

    const composition = send.mock.calls[1][0]
    expect(composition).toMatchObject({ stage: 'keyboard:composition', compositions: 2, firstAfterSec: 2.5, focusSec: 5 })
  })

  it('names a field by its test id, else its first classes, else its tag', () => {
    expect(describeField(document.querySelector('[data-testid=chat-input]')).name).toBe('chat-input')
    expect(describeField(document.querySelector('.xterm-helper-textarea')).name).toBe('xterm-helper-textarea.extra')
    expect(describeField(document.querySelector('#editable')).name).toBe('div')
  })

  it('marks the hidden helper field of the terminal by its name and its read-only attribute', () => {
    const helper = document.querySelector('.xterm-helper-textarea')
    helper.focus()
    expect(send.mock.calls[0][0]).toMatchObject({
      name: 'xterm-helper-textarea.extra', readonly: true, attributes: { inputmode: 'none' },
    })
  })

  it('never keeps what the user typed', () => {
    const field = document.querySelector('[data-testid=chat-input]')
    field.focus()
    field.value = 'a secret sentence'
    compose(field)
    field.blur()
    expect(JSON.stringify(send.mock.calls)).not.toContain('secret')
  })

  it('thins a repeat focus on the same field out, but keeps the conversions that happened in it', () => {
    const field = document.querySelector('[data-testid=chat-input]')
    field.focus()
    field.blur()
    clock += 1_000
    field.focus()
    compose(field)
    field.blur()

    expect(stages()).toEqual(['keyboard:focus', 'keyboard:composition', 'keyboard:composition'])
    expect(send.mock.calls[2][0]).toMatchObject({ compositions: 1 })
  })

  it('writes the focus line again once the window has passed, and for another field at once', () => {
    const chat = document.querySelector('[data-testid=chat-input]')
    const terminal = document.querySelector('[data-testid=terminal-input]')
    chat.focus()
    terminal.focus()
    clock += 60_000
    chat.focus()
    expect(stages().filter(stage => stage === 'keyboard:focus')).toHaveLength(3)
  })

  it('stays silent for what raises no text keyboard', () => {
    document.querySelector('#button').focus()
    document.querySelector('#check').focus()
    document.querySelector('#button').blur()
    expect(send).not.toHaveBeenCalled()
  })

  it('writes the composition line of a field the page is hidden under (= pagehide)', () => {
    document.querySelector('[data-testid=chat-input]').focus()
    window.dispatchEvent(new Event('pagehide'))
    expect(stages()).toEqual(['keyboard:focus', 'keyboard:composition'])
  })

  it('stops watching when told to', () => {
    stop()
    document.querySelector('[data-testid=chat-input]').focus()
    expect(send).not.toHaveBeenCalled()
  })
})
