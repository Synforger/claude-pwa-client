// @vitest-environment jsdom
//
// useThrottledStreamingText (= streaming 中の markdown 再パース間引き) の契約 test。
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import {
  useThrottledStreamingText,
  STREAMING_RENDER_THROTTLE_MS as MS,
} from './useThrottledStreamingText.js'

beforeEach(() => vi.useFakeTimers())
afterEach(() => vi.useRealTimers())

describe('useThrottledStreamingText', () => {
  it('streaming 中は間隔内の更新を畳み、 trailing で最新値に追い付く', () => {
    const { result, rerender } = renderHook(
      ({ text, streaming }) => useThrottledStreamingText(text, streaming),
      { initialProps: { text: 'a', streaming: true } },
    )
    expect(result.current).toBe('a')          // leading は即時
    rerender({ text: 'ab', streaming: true })
    rerender({ text: 'abc', streaming: true })
    expect(result.current).toBe('a')          // 間隔内は据え置き (= パース抑制)
    act(() => vi.advanceTimersByTime(MS + 20))
    expect(result.current).toBe('abc')        // trailing で最新値 1 回だけ
  })

  it('streaming 完了で即最終 text (= 間引き解除)', () => {
    const { result, rerender } = renderHook(
      ({ text, streaming }) => useThrottledStreamingText(text, streaming),
      { initialProps: { text: 'a', streaming: true } },
    )
    rerender({ text: 'ab', streaming: true })
    rerender({ text: 'ab final', streaming: false })
    expect(result.current).toBe('ab final')
  })

  it('非 streaming bubble は素通し (= 1 frame の遅れも無い)', () => {
    const { result, rerender } = renderHook(
      ({ text, streaming }) => useThrottledStreamingText(text, streaming),
      { initialProps: { text: 'x', streaming: false } },
    )
    rerender({ text: 'y', streaming: false })
    expect(result.current).toBe('y')
  })
})
