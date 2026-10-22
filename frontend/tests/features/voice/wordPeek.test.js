import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createWordPeek } from '../../../src/features/voice/wordPeek.js'

const frame = () => new Float32Array(512)

beforeEach(() => vi.useFakeTimers())
afterEach(() => vi.useRealTimers())

function peekWith(answers) {
  const tries = []
  const stops = []
  const peek = createWordPeek({
    everyMs: 100,
    transcribe: async (audio) => { tries.push(audio.length); return answers.shift() ?? '' },
    stopTurn: async () => { stops.push('stop') },
  })
  return { peek, tries, stops }
}

describe('createWordPeek', () => {
  it('tries the words while speaking and stops the turn once some come', async () => {
    const { peek, tries, stops } = peekWith(['', 'やめて'])   // 1 回目はあくびで言葉にならない
    peek.start()
    peek.frame(frame())
    await vi.advanceTimersByTimeAsync(100)
    peek.frame(frame())
    await vi.advanceTimersByTimeAsync(100)
    await vi.advanceTimersByTimeAsync(300)
    expect(tries).toEqual([512, 1024])   // 言葉が取れた後は試さない
    expect(stops).toEqual(['stop'])
  })

  it('does not stop again in the next stretch of the same turn, but does after it is sent', async () => {
    const { peek, tries, stops } = peekWith(['やっぱり', 'やめ', 'ねえ'])
    peek.start(); peek.frame(frame())
    await vi.advanceTimersByTimeAsync(100)
    peek.end()
    peek.start(); peek.frame(frame())   // 息継ぎの後の、 同じ発話の続き
    await vi.advanceTimersByTimeAsync(300)
    expect(stops).toEqual(['stop'])
    expect(tries).toHaveLength(1)
    peek.end(); peek.sent()
    peek.start(); peek.frame(frame())
    await vi.advanceTimersByTimeAsync(100)
    expect(stops).toEqual(['stop', 'stop'])
  })

  it('a noise that never becomes words never stops the turn', async () => {
    const { peek, stops } = peekWith([])
    peek.start(); peek.frame(frame())
    await vi.advanceTimersByTimeAsync(500)
    peek.end()
    expect(stops).toEqual([])
  })

  it('a failed try does not stop the turn and the next try still runs', async () => {
    const stops = []
    let calls = 0
    const peek = createWordPeek({
      everyMs: 100,
      transcribe: async () => { calls += 1; if (calls === 1) throw new Error('engine down'); return 'まって' },
      stopTurn: async () => { stops.push('stop') },
    })
    peek.start(); peek.frame(frame())
    await vi.advanceTimersByTimeAsync(200)
    expect(stops).toEqual(['stop'])
  })
})
