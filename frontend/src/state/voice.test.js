import { describe, it, expect, beforeEach } from 'vitest'
import { getSnapshot, subscribe, setVoiceAvailable, setVoiceOn, setVoiceError, _resetForTest } from './voice.js'

describe('state/voice', () => {
  beforeEach(() => _resetForTest())

  it('starts with no tab known to have a voice, none on, and no error', () => {
    expect(getSnapshot()).toEqual({ available: {}, on: {}, error: {} })
  })

  it('keeps what is set per tab', () => {
    setVoiceAvailable('a', true)
    setVoiceAvailable('b', false)
    setVoiceOn('a', true)
    setVoiceError('a', 'engine down')
    expect(getSnapshot()).toEqual({ available: { a: true, b: false }, on: { a: true }, error: { a: 'engine down' } })
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
})
