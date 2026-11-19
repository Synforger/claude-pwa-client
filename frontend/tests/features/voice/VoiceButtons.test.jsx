import { describe, it, expect } from 'vitest'
import { speakerState } from '../../../src/features/voice/VoiceButtons.jsx'

describe('speakerState — what the speaker button shows', () => {
  it('shows off while the speaker is off, whatever the engine and the reply', () => {
    expect(speakerState({ speaking: false, replying: true, engine: 'waking' })).toBe('off')
  })

  it('shows waking while the engine is asleep or being woken, even during a reply', () => {
    expect(speakerState({ speaking: true, replying: false, engine: 'asleep' })).toBe('waking')
    expect(speakerState({ speaking: true, replying: true, engine: 'waking' })).toBe('waking')
  })

  it('shows replying once the engine is up and a reply plays', () => {
    expect(speakerState({ speaking: true, replying: true, engine: 'ready' })).toBe('replying')
  })

  it('shows on for an engine that is up, failed, or not woken on use', () => {
    expect(speakerState({ speaking: true, replying: false, engine: 'ready' })).toBe('on')
    expect(speakerState({ speaking: true, replying: false, engine: 'failed' })).toBe('on')
    expect(speakerState({ speaking: true, replying: false, engine: null })).toBe('on')
  })
})
