import { describe, expect, it } from 'vitest'

import {
  clearPromptState,
  getSnapshot,
  ingestPromptStateEvent,
  selectFor,
  selectTypingAnswer,
  setTypingAnswer,
} from './promptState.js'

function reset() {
  // 前 test の残骸を掃く (= store は module-level、 test 間で持続する)
  const snap = getSnapshot()
  for (const sid of Object.keys(snap.bySid)) clearPromptState(sid)
}

describe('promptState store', () => {
  it('ingests a prompt_state event and selectFor returns entry', () => {
    reset()
    ingestPromptStateEvent({
      type: 'prompt_state',
      sid: 'sid1',
      state: 'text_prompt',
      category: 'password',
      excerpt: '[sudo] password for alice:',
      bypass_mode_visible: true,
      reason: 'regex:password',
      input_mode: 'none',
      options: [],
      key_requires_enter: true,
    })
    const entry = selectFor(getSnapshot(), 'sid1')
    expect(entry).not.toBeNull()
    expect(entry.state).toBe('text_prompt')
    expect(entry.category).toBe('password')
    expect(entry.excerpt).toBe('[sudo] password for alice:')
    expect(entry.bypassModeVisible).toBe(true)
    expect(entry.reason).toBe('regex:password')
    expect(entry.inputMode).toBe('none')
    expect(entry.options).toEqual([])
    expect(entry.keyRequiresEnter).toBe(true)
  })

  it('ignores events without sid or wrong type', () => {
    reset()
    ingestPromptStateEvent({ type: 'other', sid: 'x', state: 'active' })
    ingestPromptStateEvent({ type: 'prompt_state', state: 'active' })
    expect(getSnapshot().bySid).toEqual({})
  })

  it('overwrites the entry when a new state comes in for the same sid', () => {
    reset()
    ingestPromptStateEvent({
      type: 'prompt_state',
      sid: 's',
      state: 'text_prompt',
      excerpt: 'x',
    })
    ingestPromptStateEvent({
      type: 'prompt_state',
      sid: 's',
      state: 'active',
    })
    expect(selectFor(getSnapshot(), 's').state).toBe('active')
  })

  it('clearPromptState removes the entry', () => {
    reset()
    ingestPromptStateEvent({
      type: 'prompt_state',
      sid: 's',
      state: 'idle',
    })
    expect(selectFor(getSnapshot(), 's')).not.toBeNull()
    clearPromptState('s')
    expect(selectFor(getSnapshot(), 's')).toBeNull()
  })

  it('selectFor returns null on missing snapshot or sid', () => {
    reset()
    expect(selectFor(null, 'x')).toBeNull()
    expect(selectFor(getSnapshot(), null)).toBeNull()
    expect(selectFor(getSnapshot(), 'not-there')).toBeNull()
  })
})

describe('typingAnswer (= Type something 選択後の回答入力中 flag)', () => {
  it('set / clear + 待ち系以外への遷移で自動クリア', () => {
    setTypingAnswer('ses_t', true)
    expect(selectTypingAnswer(getSnapshot(), 'ses_t')).toBe(true)
    // 待ち系 (inline_tui) の event では維持
    ingestPromptStateEvent({ type: 'prompt_state', sid: 'ses_t', state: 'inline_tui' })
    expect(selectTypingAnswer(getSnapshot(), 'ses_t')).toBe(true)
    // active への遷移 (= dialog が閉じた) で自動クリア
    ingestPromptStateEvent({ type: 'prompt_state', sid: 'ses_t', state: 'active' })
    expect(selectTypingAnswer(getSnapshot(), 'ses_t')).toBe(false)
    // 手動 off も効く
    setTypingAnswer('ses_t', true)
    setTypingAnswer('ses_t', false)
    expect(selectTypingAnswer(getSnapshot(), 'ses_t')).toBe(false)
  })

  it('clearPromptState は typingAnswer も掃除する', () => {
    setTypingAnswer('ses_u', true)
    clearPromptState('ses_u')
    expect(selectTypingAnswer(getSnapshot(), 'ses_u')).toBe(false)
  })
})
