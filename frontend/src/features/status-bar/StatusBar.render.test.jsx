// @vitest-environment jsdom
//
// StatusBar の表示ロジック契約 test (= 2026-07-27 audit 充填: 従来テスト 0 件)。
// useStatus を mock して「status 値 → 表示文字列」 の変換だけを固定する。
// 特に 5h / 7d の期限切れ 0% フォールバック (= 窓切れの古い % を出し続けない) は
// 2026-07-27 に 7d 側の欠落を直したばかりの回帰点。
import { it, expect, vi, afterEach } from 'vitest'
import { render, cleanup } from '@testing-library/react'

const mockStatus = vi.fn()
vi.mock('./useStatus.js', () => ({ useStatus: (...a) => mockStatus(...a) }))
vi.mock('../../transport/connectionStatus.js', () => ({ useConnectionStatus: () => true }))

import StatusBar from './StatusBar.jsx'

afterEach(() => { cleanup(); mockStatus.mockReset() })

const NOW = Math.floor(Date.now() / 1000)

function baseStatus(over = {}) {
  return {
    model: 'claude-opus-4-8',
    five_hour_pct: 40, five_hour_resets_at: NOW + 3600,
    seven_day_pct: 70, seven_day_resets_at: NOW + 86400,
    ctx_pct: 12, mode: null, pr_links: [],
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

it('falls back to 0% when the 5h window has expired', () => {
  mockStatus.mockReturnValue(baseStatus({ five_hour_resets_at: NOW - 60 }))
  const { container } = render(<StatusBar />)
  expect(container.textContent).toContain('5h 0%')
})

it('falls back to 0% when the 7d window has expired (= 2026-07-27 fix)', () => {
  mockStatus.mockReturnValue(baseStatus({ seven_day_resets_at: NOW - 60 }))
  const { container } = render(<StatusBar />)
  expect(container.textContent).toContain('7d 0%')
  // 5h は現行のまま
  expect(container.textContent).toContain('5h 40%')
})

it('keeps raw pct while resets_at is unknown (= 0)', () => {
  mockStatus.mockReturnValue(baseStatus({ seven_day_resets_at: 0, seven_day_pct: 55 }))
  const { container } = render(<StatusBar />)
  expect(container.textContent).toContain('7d 55%')
})
