import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { createTurnTaker, join, isUnfinished } from './turnTaker.js'

const PAUSE_MS = 700
const WAIT_MS = 3000
const ENDINGS = ['、', '…', 'なんか', 'えーと']
const piece = (...values) => new Float32Array(values)
// 文字にすると、 声の値を「-」 でつないだ文になる (= 言いさしを作りたい値は words で文を差し替える)
const asText = (audio, words) => words[Array.from(audio).join('-')] ?? Array.from(audio).join('-')

function rig({ judge = async () => true, words = {}, transcribe, resumeMs = 0 } = {}) {
  const sent = []
  const written = []
  const phases = []
  const errors = []
  const taker = createTurnTaker({
    judge,
    transcribe: transcribe || (async (audio) => { written.push(Array.from(audio)); return asText(audio, words) }),
    send: (text) => sent.push(text),
    unfinished: (text) => isUnfinished(text, ENDINGS),
    pauseMs: PAUSE_MS,
    waitMs: WAIT_MS,
    resumeMs,
    onPhase: (p) => phases.push(p),
    onError: (e) => errors.push(e.message),
  })
  return { taker, sent, written, phases, errors }
}

// 声が途切れてから送るまでの残り (= 区間は、 声が PAUSE_MS 途切れた時に終わる)
const LEFT_MS = WAIT_MS - PAUSE_MS

describe('createTurnTaker — what is said goes once the speaker has finished', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  it('sends at once when Smart Turn says the speaker has finished', async () => {
    const { taker, sent, phases } = rig()
    taker.speechStart()
    await taker.speechEnd(piece(1, 2))
    expect(sent).toEqual(['1-2'])
    expect(phases).toEqual(['talking', 'judging', 'hearing', 'listening'])
  })

  it('starts writing down as the voice stops, without waiting for Smart Turn', async () => {
    let answer
    const { taker, written, sent } = rig({ judge: () => new Promise((resolve) => { answer = resolve }) })
    taker.speechStart()
    const ending = taker.speechEnd(piece(1))
    expect(written).toEqual([[1]])
    answer(true)
    await ending
    expect(written).toEqual([[1]])        // what Smart Turn waited on is not written down twice
    expect(sent).toEqual(['1'])
  })

  it('has the words ready when the wait ends, so they go at once', async () => {
    let written = 0
    const { taker, sent } = rig({
      judge: async () => false,
      transcribe: async () => { await new Promise((resolve) => setTimeout(resolve, 1500)); written += 1; return 'おはよう。' },
    })
    taker.speechStart()
    await taker.speechEnd(piece(1))
    await vi.advanceTimersByTimeAsync(WAIT_MS - PAUSE_MS)
    expect(sent).toEqual(['おはよう。'])
    expect(written).toBe(1)
  })

  it('waits while the speaker is still thinking, and sends once they stay quiet for the rest of the wait', async () => {
    const { taker, sent, phases } = rig({ judge: async () => false })
    taker.speechStart()
    await taker.speechEnd(piece(1))
    expect(sent).toEqual([])
    expect(phases.at(-1)).toBe('listening')
    await vi.advanceTimersByTimeAsync(LEFT_MS - 1)
    expect(sent).toEqual([])
    await vi.advanceTimersByTimeAsync(1)
    expect(sent).toEqual(['1'])
  })

  it('does not send words that trail off, though Smart Turn says finished, until the speaker stays quiet', async () => {
    const { taker, sent, written } = rig({ words: { 1: 'なんか、' } })
    taker.speechStart()
    await taker.speechEnd(piece(1))
    expect(sent).toEqual([])
    await vi.advanceTimersByTimeAsync(LEFT_MS)
    expect(sent).toEqual(['なんか、'])
    expect(written).toEqual([[1]])        // what was written down is sent as it was, not written again
  })

  it('joins what follows words that trailed off, and writes the whole turn down again', async () => {
    const { taker, sent, written } = rig({ words: { 1: 'えーと' } })
    taker.speechStart()
    await taker.speechEnd(piece(1))
    await vi.advanceTimersByTimeAsync(1000)
    taker.speechStart()
    await vi.advanceTimersByTimeAsync(WAIT_MS)
    expect(sent).toEqual([])
    await taker.speechEnd(piece(2))
    expect(written).toEqual([[1], [1, 2]])
    expect(sent).toEqual(['1-2'])
  })

  it('counts the wait from when the voice stopped, not from when the words came back', async () => {
    const { taker, sent } = rig({
      words: { 1: 'なんか、' },
      transcribe: async () => { await new Promise((resolve) => setTimeout(resolve, 1500)); return 'なんか、' },
    })
    taker.speechStart()
    const ending = taker.speechEnd(piece(1))
    await vi.advanceTimersByTimeAsync(1500)
    await ending
    await vi.advanceTimersByTimeAsync(LEFT_MS - 1500 - 1)
    expect(sent).toEqual([])
    await vi.advanceTimersByTimeAsync(1)
    expect(sent).toEqual(['なんか、'])
  })

  it('joins what follows a pause into the same turn', async () => {
    const answers = [false, true]
    const seen = []
    const { taker, sent } = rig({ judge: async (audio) => { seen.push(Array.from(audio)); return answers.shift() } })
    taker.speechStart()
    await taker.speechEnd(piece(1, 2))
    await vi.advanceTimersByTimeAsync(1000)
    taker.speechStart()                       // the waiting clock stops
    await vi.advanceTimersByTimeAsync(WAIT_MS)
    expect(sent).toEqual([])
    await taker.speechEnd(piece(3))
    expect(seen).toEqual([[1, 2], [1, 2, 3]])
    expect(sent).toEqual(['1-2-3'])
  })

  it('drops an answer that comes after the speaker has started again', async () => {
    let answer
    const { taker, sent } = rig({ judge: () => new Promise((resolve) => { answer = resolve }) })
    taker.speechStart()
    const ending = taker.speechEnd(piece(1))
    taker.speechStart()
    answer(true)
    await ending
    expect(sent).toEqual([])
  })

  it('does not send a turn the speaker carried on while it was being written down, and sends it with what follows', async () => {
    let done
    const texts = []
    const { taker, sent, phases } = rig({
      transcribe: (audio) => new Promise((resolve) => { texts.push(Array.from(audio)); done = () => resolve(asText(audio, {})) }),
    })
    taker.speechStart()
    const first = taker.speechEnd(piece(1))
    await vi.advanceTimersByTimeAsync(0)
    taker.speechStart()
    expect(phases.at(-1)).toBe('talking')
    done()
    await first
    expect(sent).toEqual([])
    const second = taker.speechEnd(piece(2))
    await vi.advanceTimersByTimeAsync(0)
    done()
    await second
    expect(texts).toEqual([[1], [1, 2]])
    expect(sent).toEqual(['1-2'])
  })

  it('sends at the end of speech when there is no Smart Turn', async () => {
    const { taker, sent, phases } = rig({ judge: null })
    taker.speechStart()
    await taker.speechEnd(piece(4))
    expect(sent).toEqual(['4'])
    expect(phases).not.toContain('judging')
  })

  it('sends, and says why, when Smart Turn cannot judge', async () => {
    const { taker, sent, errors } = rig({ judge: async () => { throw new Error('model gone') } })
    await taker.speechEnd(piece(5))
    expect(sent).toEqual(['5'])
    expect(errors).toEqual(['model gone'])
  })

  it('drops the turn, and says why, when it cannot be written down', async () => {
    const { taker, sent, errors } = rig({ transcribe: async () => { throw new Error('engine gone') } })
    await taker.speechEnd(piece(5))
    expect(errors).toEqual(['engine gone'])
    await taker.flush()
    expect(sent).toEqual([])
  })

  it('sends nothing for a sound that was not speech', async () => {
    const { taker, sent, phases } = rig({ words: { 9: '' } })
    await taker.speechEnd(piece(9))
    expect(sent).toEqual([])
    expect(phases.at(-1)).toBe('listening')
  })

  it('starts waiting again after a sound that was too short to be speech', async () => {
    const { taker, sent } = rig({ judge: async () => false })
    await taker.speechEnd(piece(6))
    taker.speechStart()                       // the clock stops ...
    taker.misfire()                           // ... but it was not speech
    await vi.advanceTimersByTimeAsync(WAIT_MS)
    expect(sent).toEqual(['6'])
  })

  it('sends what is waiting at once when it is flushed, words that trail off included', async () => {
    const { taker, sent } = rig({ words: { 7: 'なんか' } })
    await taker.speechEnd(piece(7))
    await taker.flush()
    expect(sent).toEqual(['なんか'])
    await vi.advanceTimersByTimeAsync(WAIT_MS)
    expect(sent).toEqual(['なんか'])
  })

  it('sends nothing once closed', async () => {
    const { taker, sent } = rig({ judge: async () => false })
    await taker.speechEnd(piece(8))
    taker.close()
    await vi.advanceTimersByTimeAsync(WAIT_MS)
    await taker.speechEnd(piece(9))
    await taker.flush()
    expect(sent).toEqual([])
  })

  it('waits resumeMs before sending what Smart Turn called finished, and sends it if nothing follows', async () => {
    const { taker, sent } = rig({ resumeMs: 400 })
    taker.speechStart()
    await taker.speechEnd(piece(1, 2))
    expect(sent).toEqual([])
    await vi.advanceTimersByTimeAsync(399)
    expect(sent).toEqual([])
    await vi.advanceTimersByTimeAsync(1)
    expect(sent).toEqual(['1-2'])
  })

  it('joins what was called finished with what the speaker goes on to say within resumeMs', async () => {
    const { taker, sent, written } = rig({ resumeMs: 400 })
    taker.speechStart()
    await taker.speechEnd(piece(1))
    await vi.advanceTimersByTimeAsync(200)
    taker.speechStart()
    await vi.advanceTimersByTimeAsync(1000)
    expect(sent).toEqual([])
    await taker.speechEnd(piece(2))
    await vi.advanceTimersByTimeAsync(400)
    expect(sent).toEqual(['1-2'])
    expect(written.at(-1)).toEqual([1, 2])
  })

  it('sends what waits for resumeMs at once when the reply starts', async () => {
    const { taker, sent } = rig({ resumeMs: 400 })
    taker.speechStart()
    await taker.speechEnd(piece(3))
    await taker.flush()
    expect(sent).toEqual(['3'])
    await vi.advanceTimersByTimeAsync(1000)
    expect(sent).toEqual(['3'])
  })
})

describe('isUnfinished — words that trail off', () => {
  it.each([
    ['なんか、', true], ['なんか', true], ['なんか。', true], ['えーと…', true], ['それでね、 えーと', true],
    ['おはよう', false], ['うん', false], ['速さはいい感じなんだけど', false], ['明日の天気を教えて。', false], ['', false],
  ])('%s → %s', (text, expected) => {
    expect(isUnfinished(text, ENDINGS)).toBe(expected)
  })
})

describe('join — the pieces of one turn, end to end', () => {
  it('keeps a single piece as it is and joins several in order', () => {
    const one = piece(1)
    expect(join([one])).toBe(one)
    expect(Array.from(join([piece(1, 2), piece(3)]))).toEqual([1, 2, 3])
  })
})
