// @vitest-environment jsdom
//
// StatusBar の表示ロジック契約 test。 useStatus を mock して「status 値 → 表示文字列」 の変換だけを固定する。
// 5h / 7d は、 数字が在って窓が戻っていない時だけ出る (= 分からない値を 0% で埋めない)。
import { it, expect, vi, afterEach } from 'vitest'
import { render, cleanup } from '@testing-library/react'

const mockStatus = vi.fn()
vi.mock('../../../src/features/status-bar/useStatus.js', () => ({ useStatus: (...a) => mockStatus(...a) }))
vi.mock('../../../src/transport/connectionStatus.js', () => ({ useConnectionStatus: () => true }))

import StatusBar from '../../../src/features/status-bar/StatusBar.jsx'

afterEach(() => { cleanup(); mockStatus.mockReset() })

const NOW = Math.floor(Date.now() / 1000)

function baseStatus(over = {}) {
  return {
    model: 'claude-opus-4-8',
    five_hour_pct: 40, five_hour_resets_at: NOW + 3600,
    seven_day_pct: 70, seven_day_resets_at: NOW + 86400,
    ctx_pct: 12, mode: null,
    ...over,
  }
}

it('renders live percentages when windows are current', () => {
  mockStatus.mockReturnValue(baseStatus())
  const { getByTestId, container } = render(<StatusBar />)
  expect(getByTestId('status-bar-model').textContent).toBe('Opus 4.8')
  expect(container.textContent).toContain('5h 40%')
  expect(container.textContent).toContain('7d 70%')
})

it('leaves out the 5h window once it has reset', () => {
  mockStatus.mockReturnValue(baseStatus({ five_hour_resets_at: NOW - 60 }))
  const { container } = render(<StatusBar />)
  expect(container.textContent).not.toContain('5h')
  expect(container.textContent).toContain('7d 70%')
})

it('leaves out the 7d window once it has reset', () => {
  mockStatus.mockReturnValue(baseStatus({ seven_day_resets_at: NOW - 60 }))
  const { container } = render(<StatusBar />)
  expect(container.textContent).not.toContain('7d')
  // 5h は現行のまま
  expect(container.textContent).toContain('5h 40%')
})

it('keeps raw pct while resets_at is unknown (= 0)', () => {
  mockStatus.mockReturnValue(baseStatus({ seven_day_resets_at: 0, seven_day_pct: 55 }))
  const { container } = render(<StatusBar />)
  expect(container.textContent).toContain('7d 55%')
})

it('shows the week and ctx alone for an account without the 5 hours', () => {
  mockStatus.mockReturnValue(baseStatus({ five_hour_pct: null, five_hour_resets_at: null }))
  const { container } = render(<StatusBar />)
  expect(container.textContent).not.toContain('5h')
  expect(container.textContent).toContain('7d 70%')
  expect(container.textContent).toContain('ctx 12%')
})

it('shows ctx alone, and no 0%, when neither window is known', () => {
  mockStatus.mockReturnValue(baseStatus({
    five_hour_pct: null, five_hour_resets_at: null, seven_day_pct: null, seven_day_resets_at: null,
  }))
  const { container } = render(<StatusBar />)
  expect(container.textContent).not.toMatch(/5h|7d|NaN| 0%/)
  expect(container.textContent).toContain('ctx 12%')
})

it('shows a real 0% of a window', () => {
  mockStatus.mockReturnValue(baseStatus({ five_hour_pct: 0 }))
  const { container } = render(<StatusBar />)
  expect(container.textContent).toContain('5h 0%')
})
