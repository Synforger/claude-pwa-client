// 設定の画面の「口座」。 口座ごとに 1 つの card を並べ、 その後に API の財布 (= 読むだけ) を並べる。
import { useT } from '../../i18n/t.js'
import AccountCard from './AccountCard.jsx'
import ApiWalletCard from './ApiWalletCard.jsx'

export default function AccountsSection({ view, nowSeconds, onSave, onContinue, onUnpin }) {
  const t = useT()
  return (
    <section className="settings-section" data-testid="settings-accounts">
      <h3>{t('settings.accounts.title')}</h3>
      {view.accounts.map(account => (
        <AccountCard
          key={account.id}
          account={account} limits={view.limits} nowSeconds={nowSeconds}
          onSave={onSave} onContinue={onContinue} onUnpin={onUnpin}
        />
      ))}
      {(view.api_accounts || []).map(wallet => <ApiWalletCard key={wallet.id} wallet={wallet} />)}
    </section>
  )
}
