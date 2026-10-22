import { describe, it, expect } from 'vitest'
import { createPlayer } from '../../../src/features/voice/player.js'

// 外から「いつ済むか」 を決められる約束。
function deferred() {
  let resolve, reject
  const promise = new Promise((res, rej) => { resolve = res; reject = rej })
  return { promise, resolve, reject }
}
const tick = () => new Promise(resolve => setTimeout(resolve, 0))

// 文は「。」 で切る。 音は文そのもの。 鳴らすのは記録するだけで、 すぐ鳴り終える。
function rig(over = {}) {
  const log = []
  const errors = []
  const player = createPlayer({
    utterances: async (_sid, text) => text.split('。').filter(Boolean).map(t => ({ mark: 'calm', text: `${t}。` })),
    sound: async (_sid, utterance) => { log.push(`make ${utterance.text}`); return utterance.text },
    play: (_sid, data) => { log.push(`play ${data}`); return { done: Promise.resolve(), stop() {} } },
    onError: (sid, error) => errors.push([sid, error.message]),
    onPlayed: () => log.push('played'),
    ...over,
  })
  return { player, log, errors }
}

describe('createPlayer — sentences are made and played in order', () => {
  it('plays the sentences of a reply in the order they were written', async () => {
    const { player, log } = rig()
    player.say('s', '一。二。三。')
    await player.idle('s')
    expect(log.filter(l => l.startsWith('play '))).toEqual(['play 一。', 'play 二。', 'play 三。'])
    expect(log.filter(l => l === 'played')).toHaveLength(3)
  })

  it('plays a second reply after the first, not across it', async () => {
    const { player, log } = rig()
    player.say('s', '一。二。')
    player.say('s', '三。')
    await player.idle('s')
    expect(log.filter(l => l.startsWith('play '))).toEqual(['play 一。', 'play 二。', 'play 三。'])
  })

  it('starts playing the first sentence before the later ones are made', async () => {
    const gates = { '一。': deferred(), '二。': deferred() }
    const { player, log } = rig({
      sound: (_sid, u) => { log.push(`ask ${u.text}`); return gates[u.text].promise },
    })
    player.say('s', '一。二。')
    await tick()
    expect(log).toEqual(['ask 一。'])           // 同時に頼むのは 1 文
    gates['一。'].resolve('一。')
    await tick()
    expect(log).toContain('play 一。')           // 2 文目の音を待たずに鳴る
    expect(log).toContain('ask 二。')
    gates['二。'].resolve('二。')
    await player.idle('s')
    expect(log.filter(l => l.startsWith('play '))).toEqual(['play 一。', 'play 二。'])
  })

  it('makes the next sentence while the current one is still playing', async () => {
    const playing = deferred()
    const { player, log } = rig({
      play: (_sid, data) => { log.push(`play ${data}`); return { done: data === '一。' ? playing.promise : Promise.resolve(), stop() {} } },
    })
    player.say('s', '一。二。')
    await tick(); await tick()
    expect(log).toContain('play 一。')
    expect(log).toContain('make 二。')
    expect(log).not.toContain('play 二。')       // 1 文目が鳴り終えるまで、 2 文目は鳴らない
    playing.resolve()
    await player.idle('s')
    expect(log).toContain('play 二。')
  })

  it('stops the sound that is playing and drops what was waiting', async () => {
    const playing = deferred()
    let stopped = 0
    const { player, log, errors } = rig({
      play: (_sid, data) => { log.push(`play ${data}`); return { done: playing.promise, stop() { stopped += 1; playing.resolve() } } },
    })
    player.say('s', '一。二。三。')
    await tick(); await tick()
    player.stop('s')
    await tick(); await tick()
    expect(stopped).toBe(1)
    expect(log.filter(l => l.startsWith('play '))).toEqual(['play 一。'])
    expect(errors).toEqual([])
  })

  it('cancels the requests it had out when stopped, and says a new reply afterwards', async () => {
    const signals = []
    const gate = deferred()
    const { player, log, errors } = rig({
      sound: (_sid, u, signal) => { signals.push(signal); return u.text === '一。' ? gate.promise : Promise.resolve(u.text) },
    })
    player.say('s', '一。')
    await tick()
    player.stop('s')
    expect(signals[0].aborted).toBe(true)
    gate.reject(new Error('aborted'))
    player.say('s', '二。')
    await player.idle('s')
    expect(log.filter(l => l.startsWith('play '))).toEqual(['play 二。'])
    expect(errors).toEqual([])                    // 止めた後に失敗した通信は、 失敗として出さない
  })

  it('reports why a sentence could not be made, drops the rest of that reply, and says the next reply', async () => {
    const { player, log, errors } = rig({
      sound: async (_sid, u) => { if (u.text === '二。') throw new Error('engine down'); return u.text },
    })
    player.say('s', '一。二。三。')
    player.say('s', '四。')
    await player.idle('s')
    expect(errors).toEqual([['s', 'engine down']])
    expect(log.filter(l => l.startsWith('play '))).toEqual(['play 一。', 'play 四。'])
  })

  it('reports why a reply could not be cut into sentences', async () => {
    const { player, errors, log } = rig({ utterances: async () => { throw new Error('too long') } })
    player.say('s', '長い。')
    await player.idle('s')
    expect(errors).toEqual([['s', 'too long']])
    expect(log).toEqual([])
  })

  it('reports a sound that could not be played', async () => {
    const { player, errors } = rig({ play: () => ({ done: Promise.reject(new Error('no audio')), stop() {} }) })
    player.say('s', '一。')
    await player.idle('s')
    expect(errors).toEqual([['s', 'no audio']])
  })

  it('says nothing for a reply with nothing to say', async () => {
    const { player, log, errors } = rig({ utterances: async () => [] })
    player.say('s', '```\ncode\n```')
    await player.idle('s')
    expect(log).toEqual([])
    expect(errors).toEqual([])
  })

  it('keeps tabs apart: stopping one leaves the other playing', async () => {
    const { player, log } = rig()
    player.say('a', '一。')
    player.say('b', '二。')
    player.stop('a')
    await player.idle('a'); await player.idle('b')
    expect(log.filter(l => l.startsWith('play '))).toEqual(['play 二。'])
  })
})

describe('createPlayer — says when it holds something to play', () => {
  it('is busy from the first reply until the last sentence of the last reply has played', async () => {
    const busy = []
    const gate = deferred()
    const { player } = rig({
      onBusy: (sid, b) => busy.push(`${sid}:${b}`),
      play: (_sid, data) => ({ done: data === '三。' ? gate.promise : Promise.resolve(), stop() {} }),
    })
    player.say('s', '一。二。')
    player.say('s', '三。')
    await tick()
    expect(busy).toEqual(['s:true'])            // 2 本目では知らせ直さない
    await tick(); await tick()
    expect(busy).toEqual(['s:true'])            // 3 文目が鳴っている間は、 まだ抱えている
    gate.resolve()
    await player.idle('s'); await tick()
    expect(busy).toEqual(['s:true', 's:false'])
  })

  it('is quiet as soon as it is stopped, and stays quiet', async () => {
    const busy = []
    const gate = deferred()
    const { player } = rig({ onBusy: (sid, b) => busy.push(b), play: () => ({ done: gate.promise, stop() {} }) })
    player.say('s', '一。二。')
    await tick(); await tick()
    player.stop('s')
    expect(busy).toEqual([true, false])
    gate.resolve()
    await tick(); await tick()
    expect(busy).toEqual([true, false])
    player.stop('s')
    expect(busy).toEqual([true, false])          // 抱えていなければ知らせない
  })
})
