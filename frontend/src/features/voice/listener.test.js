import { describe, it, expect } from 'vitest'
import { speechParts, createListener, MAX_HEARD } from './listener.js'

const reply = (uuid, ts, content) => ({ type: 'assistant', uuid, ts, message: { content } })
const text = (t) => ({ type: 'text', text: t })
const tool = (id, input, name = 'Bash') => ({ type: 'tool_use', id, name, input })

function listening(on = true) {
  const said = []
  const state = { on }
  const listener = createListener({ isOn: () => state.on, say: (sid, t) => said.push([sid, t]) })
  return { listener, said, state }
}

describe('speechParts — what in an event may be said', () => {
  it('takes the text of a reply', () => {
    expect(speechParts(reply('u1', 1, [text('できたよ。')]))).toEqual([{ key: 'u1:text', text: 'できたよ。' }])
  })

  it('leaves tool calls out, what they say they do included', () => {
    const parts = speechParts(reply('u1', 1, [
      tool('t1', { command: 'ls -la', description: 'List the files' }),
      tool('t2', { file_path: '/tmp/a.txt' }, 'Read'),
    ]))
    expect(parts).toEqual([])
  })

  it('leaves thinking out', () => {
    expect(speechParts(reply('u1', 1, [{ type: 'thinking', thinking: 'hmm' }]))).toEqual([])
  })

  it('leaves out what a subagent wrote, a reply with only spaces, and rows that are no reply', () => {
    expect(speechParts({ ...reply('u1', 1, [text('inner')]), parent_tool_use_id: 'toolu_1' })).toEqual([])
    expect(speechParts(reply('u1', 1, [text('  \n')]))).toEqual([])
    expect(speechParts({ type: 'user_message', text: 'hi' })).toEqual([])
    expect(speechParts({ type: 'assistant', uuid: 'u1' })).toEqual([])
    expect(speechParts(null)).toEqual([])
  })
})

describe('createListener — only what newly arrives is said', () => {
  it('says a reply that arrives after the voice was turned on', () => {
    const { listener, said } = listening()
    listener.observe('s', reply('old', 100, [text('前の返事。')]))
    listener.start('s')
    listener.observe('s', reply('new', 200, [text('新しい返事。')]))
    expect(said).toEqual([['s', '新しい返事。']])
  })

  it('says nothing while the voice is off', () => {
    const { listener, said } = listening(false)
    listener.observe('s', reply('a', 100, [text('一。')]))
    expect(said).toEqual([])
  })

  it('does not say what had arrived before it was turned on, even if it arrives again', () => {
    const { listener, said } = listening()
    listener.observe('s', reply('old', 100, [text('前の返事。')]))
    listener.start('s')
    listener.observe('s', reply('old', 100, [text('前の返事。')]))
    expect(said).toEqual([])
  })

  it('does not say a reply older than the moment it was turned on that it never saw', () => {
    const { listener, said } = listening()
    listener.observe('s', reply('seen', 500, [text('見た。')]))
    listener.start('s')
    listener.observe('s', reply('unseen-but-older', 400, [text('古い。')]))
    expect(said).toEqual([])
  })

  it('counts what the history load brings as heard, without saying it', () => {
    const { listener, said } = listening()
    listener.start('s')
    listener.observe('s', reply('missed', 900, [text('留守の間の返事。')]), { history: true })
    listener.observe('s', reply('missed', 900, [text('留守の間の返事。')]))
    expect(said).toEqual([])
  })

  it('says the same reply once when the stream delivers it twice', () => {
    const { listener, said } = listening()
    listener.start('s')
    listener.observe('s', reply('a', 100, [text('一度だけ。')]))
    listener.observe('s', reply('a', 100, [text('一度だけ。')]))
    expect(said).toEqual([['s', '一度だけ。']])
  })

  it('says the words written between tool calls, and not the tool calls', () => {
    const { listener, said } = listening()
    listener.start('s')
    listener.observe('s', reply('a', 100, [text('調べるね。')]))
    listener.observe('s', reply('b', 101, [tool('t1', { command: 'ls', description: 'ファイルを一覧する' })]))
    listener.observe('s', reply('c', 102, [text('3 つあったよ。')]))
    expect(said).toEqual([['s', '調べるね。'], ['s', '3 つあったよ。']])
  })

  it('does not say a reply that carries no time', () => {
    const { listener, said } = listening()
    listener.start('s')
    listener.observe('s', reply('a', undefined, [text('いつの物か分からない。')]))
    expect(said).toEqual([])
  })

  it('stops saying once turned off, and starts again from that moment when turned on', () => {
    const { listener, said, state } = listening()
    listener.start('s')
    listener.observe('s', reply('a', 100, [text('一。')]))
    listener.stop('s'); state.on = false
    listener.observe('s', reply('b', 200, [text('二。')]))
    state.on = true; listener.start('s')
    listener.observe('s', reply('c', 300, [text('三。')]))
    expect(said).toEqual([['s', '一。'], ['s', '三。']])
  })

  it('keeps tabs apart', () => {
    const { listener, said } = listening()
    listener.observe('a', reply('x', 900, [text('別のタブ。')]))
    listener.start('b')
    listener.observe('b', reply('y', 100, [text('このタブ。')]))
    expect(said).toEqual([['b', 'このタブ。']])
  })

  it('forgets the oldest of what it heard past its limit, and still does not say what came before it was on', () => {
    const { listener, said } = listening()
    listener.observe('s', reply('first', 1, [text('最初。')]))
    for (let i = 0; i < MAX_HEARD; i++) listener.observe('s', reply(`r${i}`, 2 + i, [text('途中。')]))
    listener.start('s')
    listener.observe('s', reply('first', 1, [text('最初。')]))
    expect(said).toEqual([])
  })
})

describe('createListener — a new turn sent by voice', () => {
  it('keeps the rest of the old reply quiet until the tab takes the new turn', () => {
    const said = []
    const l = createListener({ isOn: () => true, say: (_sid, line) => said.push(line) })
    const at = (ts, uuid, line) => ({ type: 'assistant', uuid, ts, message: { content: [{ type: 'text', text: line }] } })
    l.start('s')
    l.holdUntilNextTurn('s')
    l.observe('s', at(10, 'old', '前の返事の続き。'))
    l.observe('s', { type: 'user_message', uuid: 'u', ts: 11, text: '[voice] 次の話' })
    l.observe('s', at(12, 'new', '新しい返事。'))
    expect(said).toEqual(['新しい返事。'])
  })
})
