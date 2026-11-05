// Pinning a tab to its account: the 📌 before the account label of a pinned tab, and the entry of the ⋯ menu that
// pins or unpins it. The backend never moves a pinned tab to its fallback account (`docs/reference/account-fallback.md`).
//
// Both appear only where the account label does: when two or more accounts are configured.
import { useT } from '../../i18n/t.js'

/** The 📌 of a pinned tab. */
export function AccountPinMark({ session, accountCount }) {
  const t = useT()
  if (accountCount <= 1 || session.account_pinned !== true) return null
  return (
    <span className="drawer-item-pin" title={t('drawer.account_pin.mark')} data-testid="session-account-pinned">📌</span>
  )
}

/** The menu entry that pins an unpinned tab and unpins a pinned one, with the separator above it. */
export function AccountPinMenuItem({ session, accountCount, onSetPinned }) {
  const t = useT()
  if (accountCount <= 1 || !onSetPinned) return null
  const pinned = session.account_pinned === true
  return (
    <>
      <div className="drawer-popup-sep" />
      <button onClick={() => onSetPinned(session.id, !pinned)} data-testid="session-account-pin-toggle">
        {pinned ? t('drawer.account_pin.off') : t('drawer.account_pin.on')}
      </button>
    </>
  )
}
