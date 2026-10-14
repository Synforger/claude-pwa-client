import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { createTurnTaker, STOP_MS, VAD_STOP_MS, join } from './turnTaker.js'

const piece = (...values) => new Float32Array(values)

function rig({ judge = async () => true } = {}) {
  const heard = []
  const phases = []
  const errors = []
  const taker = createTurnTaker({
    judge,
    hear: async (audio) => { heard.push(Array.from(audio)) },
    onPhase: (p) => phases.push(p),
    onError: (e) => errors.push(e.message),
  })
  return { taker, heard, phases, errors }
}

describe('createTurnTaker — what is said goes once the speaker has finished', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  it('sends at once when Smart Turn says the speaker has finished', async () => {
    const { taker, heard, phases } = rig()
    taker.speechStart()
    await taker.speechEnd(piece(1, 2))
    expect(heard).toEqual([[1, 2]])
    expect(phases).toEqual(['talking', 'judging', 'hearing', 'listening'])
  })

  it('waits while the speaker is still thinking, and sends once they stay quiet for the rest of three seconds', async () => {
    const { taker, heard, phases } = rig({ judge: async () => false })
    taker.speechStart()
    await taker.speechEnd(piece(1))
    expect(heard).toEqual([])
    expect(phases.at(-1)).toBe('listening')
    await vi.advanceTimersByTimeAsync(STOP_MS - VAD_STOP_MS - 1)
    expect(heard).toEqual([])
    await vi.advanceTimersByTimeAsync(1)
    expect(heard).toEqual([[1]])
  })

  it('joins what follows a pause into the same turn', async () => {
    const answers = [false, true]
    const seen = []
    const { taker, heard } = rig({ judge: async (audio) => { seen.push(Array.from(audio)); return answers.shift() } })
    taker.speechStart()
    await taker.speechEnd(piece(1, 2))
    await vi.advanceTimersByTimeAsync(1000)
    taker.speechStart()                       // the waiting clock stops
    await vi.advanceTimersByTimeAsync(STOP_MS)
    expect(heard).toEqual([])
    await taker.speechEnd(piece(3))
    expect(seen).toEqual([[1, 2], [1, 2, 3]])
    expect(heard).toEqual([[1, 2, 3]])
  })

  it('drops an answer that comes after the speaker has started again', async () => {
    let answer
    const { taker, heard } = rig({ judge: () => new Promise((resolve) => { answer = resolve }) })
    taker.speechStart()
    const ending = taker.speechEnd(piece(1))
    taker.speechStart()
    answer(true)
    await ending
    expect(heard).toEqual([])
  })

  it('sends at the end of speech when there is no Smart Turn', async () => {
    const { taker, heard, phases } = rig({ judge: null })
    taker.speechStart()
    await taker.speechEnd(piece(4))
    expect(heard).toEqual([[4]])
    expect(phases).not.toContain('judging')
  })

  it('sends, and says why, when Smart Turn cannot judge', async () => {
    const { taker, heard, errors } = rig({ judge: async () => { throw new Error('model gone') } })
    await taker.speechEnd(piece(5))
    expect(heard).toEqual([[5]])
    expect(errors).toEqual(['model gone'])
  })

  it('starts waiting again after a sound that was too short to be speech', async () => {
    const { taker, heard } = rig({ judge: async () => false })
    await taker.speechEnd(piece(6))
    taker.speechStart()                       // the clock stops ...
    taker.misfire()                           // ... but it was not speech
    await vi.advanceTimersByTimeAsync(STOP_MS)
    expect(heard).toEqual([[6]])
  })

  it('sends what is waiting at once when it is flushed', async () => {
    const { taker, heard } = rig({ judge: async () => false })
    await taker.speechEnd(piece(7))
    await taker.flush()
    expect(heard).toEqual([[7]])
    await vi.advanceTimersByTimeAsync(STOP_MS)
    expect(heard).toEqual([[7]])
  })

  it('sends nothing once closed', async () => {
    const { taker, heard } = rig({ judge: async () => false })
    await taker.speechEnd(piece(8))
    taker.close()
    await vi.advanceTimersByTimeAsync(STOP_MS)
    await taker.speechEnd(piece(9))
    await taker.flush()
    expect(heard).toEqual([])
  })

  it('says it is writing down while an earlier turn is still being heard', async () => {
    let done
    const phases = []
    const taker = createTurnTaker({
      judge: async () => true, hear: () => new Promise((resolve) => { done = resolve }), onPhase: (p) => phases.push(p),
    })
    const first = taker.speechEnd(piece(1))
    await vi.advanceTimersByTimeAsync(0)
    taker.speechStart()
    expect(phases.at(-1)).toBe('talking')
    done()
    await first
    expect(phases.at(-1)).toBe('listening')
  })
})

describe('join — the pieces of one turn, end to end', () => {
  it('keeps a single piece as it is and joins several in order', () => {
    const one = piece(1)
    expect(join([one])).toBe(one)
    expect(Array.from(join([piece(1, 2), piece(3)]))).toEqual([1, 2, 3])
  })
})
