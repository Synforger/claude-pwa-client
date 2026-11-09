// 設定の画面の「口座」。 口座ごとに 1 つの card を並べる。
import { useT } from '../../i18n/t.js'
import AccountCard from './AccountCard.jsx'

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
    </section>
  )
}
