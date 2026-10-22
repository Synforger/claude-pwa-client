import { describe, it, expect } from 'vitest'
import { hideVoiceInputMark, VOICE_INPUT_MARK } from '../../../src/features/voice/inputMark.js'

describe('hideVoiceInputMark — the bubble shows what was typed', () => {
  it('is the mark the backend puts at the head', () => {
    expect(VOICE_INPUT_MARK).toBe('[voice]')
  })

  it('takes the mark off the head', () => {
    expect(hideVoiceInputMark('[voice] 今日の予定は？')).toBe('今日の予定は？')
    expect(hideVoiceInputMark('[voice] a\nb')).toBe('a\nb')
    expect(hideVoiceInputMark('[voice] [添付ファイル: /tmp/a.png]')).toBe('[添付ファイル: /tmp/a.png]')
  })

  it('leaves a mark that is not at the head, and other text', () => {
    expect(hideVoiceInputMark('印は [voice] と書く')).toBe('印は [voice] と書く')
    expect(hideVoiceInputMark('[voices] 別の語')).toBe('[voices] 別の語')
    expect(hideVoiceInputMark(undefined)).toBe(undefined)
  })
})
