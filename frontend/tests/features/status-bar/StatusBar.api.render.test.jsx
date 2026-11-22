// @vitest-environment jsdom
//
// The bar of an API tab (no Claude Code behind it): its own status row gives the context amount and the wallet's spend
// this month, and nothing of a Claude tab's (no model, no 5h / 7d / ctx %, which would read NaN%).
import { it, expect, vi, afterEach } from 'vitest'
import { render, cleanup } from '@testing-library/react'

const mockStatus = vi.fn()
vi.mock('../../../src/features/status-bar/useStatus.js', () => ({ useStatus: (...a) => mockStatus(...a) }))
vi.mock('../../../src/transport/connectionStatus.js', () => ({ useConnectionStatus: () => true }))

import StatusBar from '../../../src/features/status-bar/StatusBar.jsx'

afterEach(() => { cleanup(); mockStatus.mockReset() })

const apiRow = (over = {}) => ({
  kind: 'api', context_tokens: 12300,
  spend: { month: '2026-11', spent: 123, limit: 1000, currency: 'JPY', updated_at: '2026-11-18T12:00:00+09:00' },
  ...over,
})

it('shows the context amount and this month\'s spend against the limit', () => {
  mockStatus.mockReturnValue(apiRow())
  const { getByTestId } = render(<StatusBar />)
  expect(getByTestId('status-bar-api-context').textContent).toContain('12.3k')
  expect(getByTestId('status-bar-api-spend').textContent).toContain('123 / 1,000 JPY')
})

it('shows none of what a Claude tab\'s bar shows, and never NaN', () => {
  mockStatus.mockReturnValue(apiRow())
  const { container, queryByTestId } = render(<StatusBar />)
  expect(queryByTestId('status-bar-model')).toBeNull()
  expect(container.textContent).not.toMatch(/NaN|5h|7d|%/)
})

it('shows --- for an amount and a spend that are not known, never 0', () => {
  mockStatus.mockReturnValue(apiRow({ context_tokens: null, spend: null }))
  const { getByTestId } = render(<StatusBar />)
  expect(getByTestId('status-bar-api-context').textContent).toContain('---')
  expect(getByTestId('status-bar-api-spend').textContent).toContain('---')
  expect(getByTestId('status-bar-api-context').textContent).not.toMatch(/\b0\b/)
})

it('leaves a Claude tab\'s bar as it was', () => {
  mockStatus.mockReturnValue({ model: 'claude-opus-4-8', five_hour_pct: 40, five_hour_resets_at: 0, seven_day_pct: 70,
    seven_day_resets_at: 0, ctx_pct: 12, mode: null })
  const { container, queryByTestId } = render(<StatusBar />)
  expect(queryByTestId('status-bar-api-context')).toBeNull()
  expect(container.textContent).toContain('5h 40%')
})

it('shows a tab\'s own amount without a limit, next to the limit the tabs share', () => {
  mockStatus.mockReturnValue(apiRow({
    spend_scope: 'tab',
    spend: { month: '2026-11', spent: 0.5, limit: 50, currency: 'USD' },
    wallet_spend: { month: '2026-11', spent: 12, limit: 200, currency: 'USD' },
  }))
  const { getByTestId } = render(<StatusBar />)
  expect(getByTestId('status-bar-api-spend').textContent).toContain('0.5 USD')
  expect(getByTestId('status-bar-api-spend').textContent).not.toContain('50')
  expect(getByTestId('status-bar-api-wallet').textContent).toContain('12 / 200 USD')
})

it('shows a tab\'s amount that has no limit, and no shared line while the wallet has no figure', () => {
  mockStatus.mockReturnValue(apiRow({
    spend_scope: 'tab', spend: { month: '2026-11', spent: 0.5, limit: null, currency: 'USD' }, wallet_spend: null,
  }))
  const { getByTestId, queryByTestId } = render(<StatusBar />)
  expect(getByTestId('status-bar-api-spend').textContent).toContain('0.5 USD')
  expect(queryByTestId('status-bar-api-wallet')).toBeNull()
})
