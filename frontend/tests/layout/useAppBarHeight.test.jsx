// @vitest-environment jsdom
//
// The height of the bar at the top is measured, not decided: it goes to the host as the CSS variable the docked tab list
// starts below, once at the start and again each time the bar changes size, and nothing observes it after the page is left.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, cleanup } from '@testing-library/react'
import { useRef } from 'react'
import { useAppBarHeight, APP_BAR_HEIGHT_VAR } from '../../src/layout/useAppBarHeight.js'

let observers
let barHeight

class FakeResizeObserver {
  constructor(callback) {
    this.callback = callback
    this.observed = []
    this.disconnected = false
    observers.push(this)
  }
  observe(target) { this.observed.push(target) }
  disconnect() { this.disconnected = true }
}

function Host() {
  const hostRef = useRef(null)
  const barRef = useRef(null)
  useAppBarHeight(hostRef, barRef)
  return (
    <div ref={hostRef} data-testid="host">
      <div ref={barRef} data-testid="bar" />
    </div>
  )
}

beforeEach(() => {
  observers = []
  barHeight = 30
  vi.stubGlobal('ResizeObserver', FakeResizeObserver)
  vi.spyOn(Element.prototype, 'getBoundingClientRect').mockImplementation(() => ({ height: barHeight }))
})
afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('the height of the bar at the top', () => {
  it('goes to the host before anything is observed', () => {
    const { getByTestId } = render(<Host />)
    expect(getByTestId('host').style.getPropertyValue(APP_BAR_HEIGHT_VAR)).toBe('30px')
  })

  it('goes to the host again when the bar changes size', () => {
    const { getByTestId } = render(<Host />)
    barHeight = 52
    observers[0].callback()
    expect(getByTestId('host').style.getPropertyValue(APP_BAR_HEIGHT_VAR)).toBe('52px')
  })

  it('observes the bar and nothing else, and stops when the page is left', () => {
    const { getByTestId, unmount } = render(<Host />)
    expect(observers).toHaveLength(1)
    expect(observers[0].observed).toEqual([getByTestId('bar')])
    unmount()
    expect(observers[0].disconnected).toBe(true)
  })

  it('still gives the height where the browser has no ResizeObserver', () => {
    vi.stubGlobal('ResizeObserver', undefined)
    const { getByTestId } = render(<Host />)
    expect(getByTestId('host').style.getPropertyValue(APP_BAR_HEIGHT_VAR)).toBe('30px')
  })
})
