// @vitest-environment jsdom
//
// Pinning a tab to its account: the 📌 of a pinned tab and the menu entry that pins or unpins it show only where the
// account label shows (two or more accounts configured).
import { describe, it, expect, afterEach, vi } from 'vitest'
import { render, cleanup, fireEvent } from '@testing-library/react'
import { AccountPinMark, AccountPinMenuItem } from '../../../src/features/session-drawer/AccountPin.jsx'

afterEach(cleanup)

const tab = (over = {}) => ({ id: 'ses_a', title: 'T', account_id: 'work', ...over })

describe('AccountPinMark', () => {
  it('shows 📌 on a pinned tab when two accounts are configured', () => {
    const { getByTestId } = render(<AccountPinMark session={tab({ account_pinned: true })} accountCount={2} />)
    expect(getByTestId('session-account-pinned').textContent).toBe('📌')
  })

  it('shows nothing on a tab that is not pinned, or whose pin is not true', () => {
    for (const session of [tab(), tab({ account_pinned: false }), tab({ account_pinned: null }), tab({ account_pinned: 'yes' })]) {
      const { queryByTestId, unmount } = render(<AccountPinMark session={session} accountCount={2} />)
      expect(queryByTestId('session-account-pinned')).toBeNull()
      unmount()
    }
  })

  it('shows nothing when only one account is configured, pinned or not', () => {
    const { queryByTestId } = render(<AccountPinMark session={tab({ account_pinned: true })} accountCount={1} />)
    expect(queryByTestId('session-account-pinned')).toBeNull()
  })
})

describe('AccountPinMenuItem', () => {
  it('offers to pin a tab that is not pinned, and asks for the pin', () => {
    const onSetPinned = vi.fn()
    const { getByTestId } = render(<AccountPinMenuItem session={tab()} accountCount={2} onSetPinned={onSetPinned} />)
    fireEvent.click(getByTestId('session-account-pin-toggle'))
    expect(onSetPinned).toHaveBeenCalledWith('ses_a', true)
  })

  it('offers to unpin a pinned tab, and asks for the pin to go', () => {
    const onSetPinned = vi.fn()
    const { getByTestId } = render(
      <AccountPinMenuItem session={tab({ account_pinned: true })} accountCount={3} onSetPinned={onSetPinned} />,
    )
    fireEvent.click(getByTestId('session-account-pin-toggle'))
    expect(onSetPinned).toHaveBeenCalledWith('ses_a', false)
  })

  it('words the two entries differently', () => {
    const wording = (session) => {
      const { getByTestId, unmount } = render(<AccountPinMenuItem session={session} accountCount={2} onSetPinned={() => {}} />)
      const text = getByTestId('session-account-pin-toggle').textContent
      unmount()
      return text
    }
    expect(wording(tab())).not.toBe(wording(tab({ account_pinned: true })))
    expect(wording(tab())).not.toMatch(/^drawer\./)          // a real wording, not the key
  })

  it('is not in the menu when only one account is configured', () => {
    const { queryByTestId } = render(<AccountPinMenuItem session={tab()} accountCount={1} onSetPinned={() => {}} />)
    expect(queryByTestId('session-account-pin-toggle')).toBeNull()
  })
})
