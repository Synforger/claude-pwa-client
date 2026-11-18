// @vitest-environment jsdom
//
// The wallets of the settings screen's accounts section: read-only rows after the accounts, with this month's spend
// against the limit, or `---` when the wallet has no figure. A wallet is no account (nothing is routed to it).
import { describe, it, expect, afterEach } from 'vitest'
import { render, cleanup } from '@testing-library/react'
import ApiWalletCard from '../../../src/features/settings/ApiWalletCard.jsx'
import AccountsSection from '../../../src/features/settings/AccountsSection.jsx'

afterEach(cleanup)

const wallet = (over = {}) => ({
  id: 'api', display_name: 'API',
  spend: { month: '2026-11', spent: 123, limit: 1000, currency: 'JPY', updated_at: null }, ...over,
})

describe('ApiWalletCard', () => {
  it('shows the name and this month\'s spend against the limit', () => {
    const { getByTestId } = render(<ApiWalletCard wallet={wallet()} />)
    expect(getByTestId('settings-api-wallet-name').textContent).toBe('API')
    expect(getByTestId('settings-api-wallet-spend').textContent).toContain('123 / 1,000 JPY')
  })

  it('shows --- while the wallet has no figure, never 0', () => {
    const { getByTestId } = render(<ApiWalletCard wallet={wallet({ spend: null })} />)
    expect(getByTestId('settings-api-wallet-spend').textContent).toContain('---')
    expect(getByTestId('settings-api-wallet-spend').textContent).not.toMatch(/\b0\b/)
  })

  it('has nothing to edit: no field and no save button', () => {
    const { container } = render(<ApiWalletCard wallet={wallet()} />)
    expect(container.querySelector('input, button')).toBeNull()
  })
})

describe('AccountsSection', () => {
  const view = (apiAccounts) => ({
    accounts: [], limits: {}, api_accounts: apiAccounts,
  })

  it('lists the wallets after the accounts, one row each', () => {
    const { getAllByTestId } = render(
      <AccountsSection view={view([wallet(), wallet({ id: 'second', display_name: 'Second', spend: null })])}
        nowSeconds={0} onSave={() => {}} onContinue={() => {}} onUnpin={() => {}} />,
    )
    expect(getAllByTestId('settings-api-wallet-name').map(node => node.textContent)).toEqual(['API', 'Second'])
  })

  it('shows no wallet row for a backend that sends none (an older backend, or no wallet declared)', () => {
    const { queryByTestId } = render(
      <AccountsSection view={{ accounts: [], limits: {} }} nowSeconds={0} onSave={() => {}} onContinue={() => {}} onUnpin={() => {}} />,
    )
    expect(queryByTestId('settings-api-wallet-name')).toBeNull()
  })
})
