import { describe, it, expect, beforeEach } from 'vitest'
import { markVoiceInput, hideVoiceInputMark, VOICE_INPUT_MARK } from './inputMark.js'
import { voiceInputText } from './voice.js'
import { setVoiceOn, _resetForTest } from '../../state/voice.js'

describe('markVoiceInput — the text sent while the voice is on says so at its head', () => {
  it('puts the mark and one space before the text', () => {
    expect(VOICE_INPUT_MARK).toBe('[voice]')
    expect(markVoiceInput('今日の予定は？')).toBe('[voice] 今日の予定は？')
  })

  it('keeps every line of a longer text as it was', () => {
    expect(markVoiceInput('一つ目\n二つ目')).toBe('[voice] 一つ目\n二つ目')
  })

  it('leaves a text whose head claude reads as a command, shell or memory', () => {
    expect(markVoiceInput('/compact')).toBe('/compact')
    expect(markVoiceInput('! ls')).toBe('! ls')
    expect(markVoiceInput('# 覚えておいて')).toBe('# 覚えておいて')
  })

  it('does not mark a text twice', () => {
    expect(markVoiceInput('[voice] もう付いている')).toBe('[voice] もう付いている')
  })

  it('leaves an empty text and what is not text', () => {
    expect(markVoiceInput('')).toBe('')
    expect(markVoiceInput('   ')).toBe('   ')
    expect(markVoiceInput(undefined)).toBe(undefined)
  })
})

describe('hideVoiceInputMark — the bubble shows what was typed', () => {
  it('takes the mark off the head', () => {
    expect(hideVoiceInputMark('[voice] 今日の予定は？')).toBe('今日の予定は？')
    expect(hideVoiceInputMark(markVoiceInput('a\nb'))).toBe('a\nb')
  })

  it('leaves a mark that is not at the head, and other text', () => {
    expect(hideVoiceInputMark('印は [voice] と書く')).toBe('印は [voice] と書く')
    expect(hideVoiceInputMark('[voices] 別の語')).toBe('[voices] 別の語')
    expect(hideVoiceInputMark(undefined)).toBe(undefined)
  })
})

describe('voiceInputText — only a tab whose toggle is on marks what it sends', () => {
  beforeEach(() => _resetForTest())

  it('marks the text of a tab that is on, and only that tab', () => {
    setVoiceOn('ses_on', true)
    expect(voiceInputText('ses_on', 'こんにちは')).toBe('[voice] こんにちは')
    expect(voiceInputText('ses_off', 'こんにちは')).toBe('こんにちは')
  })

  it('stops marking once the toggle is off again', () => {
    setVoiceOn('ses_on', true)
    setVoiceOn('ses_on', false)
    expect(voiceInputText('ses_on', 'こんにちは')).toBe('こんにちは')
  })
})
