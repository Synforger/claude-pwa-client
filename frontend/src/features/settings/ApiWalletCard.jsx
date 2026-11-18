// A wallet of the settings screen's accounts section (`backend/api_tabs/`): what an API tab spends from, read-only.
// It sits after the accounts and is no account: nothing is routed to it, and its limit is the program's, not a line
// the screen sets. Shows this month's spend against the limit, or `---` while the wallet has no figure.
import { useT } from '../../i18n/t.js'
import { formatSpend } from '../../_common/apiTab.js'

export default function ApiWalletCard({ wallet }) {
  const t = useT()
  const spend = formatSpend(wallet.spend)
  return (
    <section className="settings-card" data-testid={`settings-api-wallet-${wallet.id}`}>
      <header className="settings-card-head">
        <span className="settings-card-name" data-testid="settings-api-wallet-name">{wallet.display_name}</span>
        <span className="settings-badge">{t('settings.api_wallet.badge')}</span>
      </header>
      <div className="settings-note" data-testid="settings-api-wallet-spend">
        {t('settings.api_wallet.spend')} {spend ?? <span className="settings-dim">---</span>}
      </div>
      <div className="settings-note">{t('settings.api_wallet.hint')}</div>
    </section>
  )
}
