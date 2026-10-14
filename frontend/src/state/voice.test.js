import { describe, it, expect, beforeEach } from 'vitest'
import {
  getSnapshot, subscribe, setVoiceAvailable, setVoiceMarks, setVoiceOn, setVoiceError, setVoiceListen, setVoiceTurn, setVoicePhase,
  setVoiceSpeaking,
  _resetForTest,
} from './voice.js'

describe('state/voice', () => {
  beforeEach(() => _resetForTest())

  it('starts with no tab known to have a voice, none on, and no error', () => {
    expect(getSnapshot()).toEqual({ available: {}, marks: {}, on: {}, error: {}, listen: {}, turn: {}, phase: {}, speaking: {} })
  })

  it('keeps what is set per tab', () => {
    setVoiceAvailable('a', true)
    setVoiceAvailable('b', false)
    setVoiceOn('a', true)
    setVoiceError('a', 'engine down')
    setVoiceMarks('a', ['calm', 'happy'])
    setVoiceListen('a', true)
    setVoiceTurn('a', true)
    setVoicePhase('a', 'talking')
    setVoiceSpeaking('a', true)
    expect(getSnapshot()).toEqual({
      available: { a: true, b: false }, marks: { a: ['calm', 'happy'] }, on: { a: true }, error: { a: 'engine down' },
      listen: { a: true }, turn: { a: true }, phase: { a: 'talking' }, speaking: { a: true } })
  })

  it('keeps only true flags, and only the known phases of a conversation', () => {
    setVoiceListen('a', false); setVoiceListen('b', 'yes'); setVoiceTurn('c', 1)
    expect(getSnapshot().listen).toEqual({})
    expect(getSnapshot().turn).toEqual({})
    setVoicePhase('a', 'hearing'); setVoicePhase('b', 'recording')
    expect(getSnapshot().phase).toEqual({ a: 'hearing' })
    setVoicePhase('a', null); setVoiceSpeaking('a', false)
    expect(getSnapshot().phase).toEqual({})
    expect(getSnapshot().speaking).toEqual({})
  })

  it('drops the entry when the voice is turned off or the error is cleared', () => {
    setVoiceOn('a', true); setVoiceError('a', 'x')
    setVoiceOn('a', false); setVoiceError('a', null)
    expect(getSnapshot().on).toEqual({})
    expect(getSnapshot().error).toEqual({})
  })

  it('does not notify when nothing changed', () => {
    setVoiceOn('a', true)
    let calls = 0
    const off = subscribe(() => { calls += 1 })
    setVoiceOn('a', true); setVoiceOn('b', false); setVoiceError('a', null); setVoiceAvailable('a', false)
    off()
    expect(calls).toBe(1)   // 変わったのは available.a だけ
  })

  it('keeps the same list of marks when it is set again with the same names', () => {
    setVoiceMarks('a', ['calm', 'happy'])
    const before = getSnapshot().marks.a
    let calls = 0
    const off = subscribe(() => { calls += 1 })
    setVoiceMarks('a', ['calm', 'happy']); setVoiceMarks('b', [])
    expect(getSnapshot().marks.a).toBe(before)
    expect(calls).toBe(0)
    setVoiceMarks('a', []); off()
    expect(getSnapshot().marks).toEqual({})
    expect(calls).toBe(1)
  })
})
