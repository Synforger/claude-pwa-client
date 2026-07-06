// @vitest-environment jsdom
//
// PromptStateBanner の tui 確定待ち (= TUI_CONFIRM_MS) の契約 test。
//
// 背景: 読み込み / SSE 再接続の初回 snapshot や poll の瞬間的な alternate_on 誤観測で
// 一発 tui event が届くと、 banner が「TUI running — use terminal view」 を一瞬表示して
// すぐ消える。 tui のみ「継続して観測されたら表示」 の確定待ちを掛け、 次 poll の復帰
// 遷移が先に届けば一度も表示しない。 text_prompt / inline_tui は quick-reply の即答性が
// 価値なので即時表示のまま (= ここも contract として固定する)。
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { render, act, cleanup } from '@testing-library/react'
import { PromptStateBanner, TUI_CONFIRM_MS } from './PromptStateBanner.jsx'
import { ingestPromptStateEvent, clearPromptState } from '../../state/promptState.js'

const SID = 'ses_banner_test'

function ingest(state, extra = {}) {
  act(() => {
    ingestPromptStateEvent({ type: 'prompt_state', sid: SID, state, ...extra })
  })
}

beforeEach(() => {
  vi.useFakeTimers()
})

afterEach(() => {
  cleanup()
  act(() => clearPromptState(SID))
  vi.useRealTimers()
})

const banner = (container) => container.querySelector('[data-testid="prompt-state-banner"]')

describe('PromptStateBanner tui 確定待ち', () => {
  it('tui は即時には出ず、 TUI_CONFIRM_MS 継続観測で出る', () => {
    const { container } = render(<PromptStateBanner sid={SID} />)
    ingest('tui', { excerpt: 'some tui screen' })
    expect(banner(container)).toBeNull()
    act(() => vi.advanceTimersByTime(TUI_CONFIRM_MS + 20))
    expect(banner(container)).toBeTruthy()
    expect(container.textContent).toContain('TUI running')
  })

  it('確定前に復帰遷移 (active) が届けば一度も出ない', () => {
    const { container } = render(<PromptStateBanner sid={SID} />)
    ingest('tui')
    act(() => vi.advanceTimersByTime(TUI_CONFIRM_MS / 2))
    ingest('active')
    expect(banner(container)).toBeNull()
    act(() => vi.advanceTimersByTime(TUI_CONFIRM_MS * 2))
    expect(banner(container)).toBeNull()
  })

  it('tui 継続中の excerpt 変化 publish で banner が点滅しない (= 起点は遷移時刻)', () => {
    const { container } = render(<PromptStateBanner sid={SID} />)
    ingest('tui', { excerpt: 'screen v1' })
    act(() => vi.advanceTimersByTime(TUI_CONFIRM_MS + 20))
    expect(banner(container)).toBeTruthy()
    ingest('tui', { excerpt: 'screen v2' })
    expect(banner(container)).toBeTruthy()
  })

  it('text_prompt / inline_tui は確定待ちなしで即時表示', () => {
    const { container } = render(<PromptStateBanner sid={SID} />)
    ingest('text_prompt', { excerpt: 'password:' })
    expect(banner(container)).toBeTruthy()
    ingest('inline_tui', { excerpt: '❯ 1. Yes\n  2. No', input_mode: 'arrows' })
    expect(banner(container)).toBeTruthy()
  })
})
