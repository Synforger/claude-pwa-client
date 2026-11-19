import { useT } from '../../i18n/t.js'
import { holderOf } from './ticketGroups.js'

// 票の件を時刻の順に並べる。 本文は素の文字で出す (= Markdown にもリンクにも画像にもしない。 タブが書いた文が別の物に
// 見えないように)。 操作者の原文 (= `operator` の件) は上に固定で出すので、 ここでは並べない。

const KINDS = ['opened', 'operator', 'added', 'asked', 'passed', 'closed', 'answered', 'delivered', 'returned', 'seen']

/** 件を書いた者の名前: タブの名前、 無ければ (= client が書いた件) client。 */
function writerName(entry, t) {
  if (entry.hidden) return ''
  return entry.tab_title || (entry.tab ? entry.tab : t('ticket.writer_client'))
}

/** 持つタブの id を、 読める名前にする (= この機械のタブは一覧の名前、 別の機械のタブは「<機械> のタブ」)。 */
export function tabName(id, tabNames, t) {
  const holder = holderOf(id)
  if (holder.kind === 'none') return t('ticket.holder_none')
  if (holder.kind === 'machine') return t('tickets.holder_machine', { machine: holder.machine })
  return tabNames[id] || id
}

function summaryOf(entry, tabNames, t) {
  switch (entry.kind) {
    case 'passed':
      return t('ticket.passed_to', { to: tabName(entry.to, tabNames, t) })
    case 'returned':
      return t('ticket.returned_to', { from: tabName(entry.from, tabNames, t), to: tabName(entry.to, tabNames, t) })
    case 'delivered':
      return t(`ticket.delivered_${entry.result}`, { to: tabName(entry.to, tabNames, t) })
    case 'asked':
      return entry.ask_kind ? t(`tickets.wants_${entry.ask_kind}`) : ''
    case 'answered':
      return entry.recommended ? t('ticket.answered_recommended') : ''
    default:
      return ''
  }
}

const timeOf = (iso) => {
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleString([], { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}

export default function TicketEntries({ entries, tabNames }) {
  const t = useT()
  return (
    <ol className="ticket-entries" data-testid="ticket-entries">
      {entries.map((entry, index) => {
        const kind = KINDS.includes(entry.kind) ? entry.kind : 'added'
        const summary = summaryOf(entry, tabNames, t)
        return (
          <li key={`${entry.at}-${index}`} className={`ticket-entry ticket-entry-${kind}`} data-testid="ticket-entry" data-kind={kind}>
            <div className="ticket-entry-head">
              <span className="ticket-entry-kind">{t(`ticket.kind_${kind}`)}</span>
              {writerName(entry, t) && <span className="ticket-entry-writer">{writerName(entry, t)}</span>}
              {summary && <span className="ticket-entry-summary">{summary}</span>}
              <span className="ticket-entry-time">{timeOf(entry.at)}</span>
            </div>
            {entry.title && <div className="ticket-entry-title">{entry.title}</div>}
            {entry.text && <div className="ticket-entry-text">{entry.text}</div>}
            {entry.recommend && (
              <div className="ticket-entry-recommend">
                <span className="ticket-entry-recommend-label">{t('ticket.recommend')}</span> {entry.recommend}
              </div>
            )}
          </li>
        )
      })}
    </ol>
  )
}
