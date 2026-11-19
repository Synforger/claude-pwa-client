import { useMemo, useSyncExternalStore } from 'react'
import { useT } from '../../i18n/t.js'
import { setOverlay, subscribe as subscribeUi, getSnapshot as getUiSnapshot } from '../../state/ui.js'
import { subscribe as subscribeSessions, getSnapshot as getSessionsSnapshot } from '../../state/sessions.js'
import { subscribe as subscribeTickets, getSnapshot as getTicketsSnapshot } from '../../state/tickets.js'
import { isApiTab } from '../../_common/apiTab.js'
import { useEscape } from '../../_common/useEscape.js'
import '../../_common/Modal.css'
import './Tickets.css'
import TicketEntries from './TicketEntries.jsx'
import TicketLower from './TicketLower.jsx'
import { ticketLabel } from './ticketGroups.js'
import { useTicketDetail } from './useTicketDetail.js'

// 票の画面 (= 📌 の一覧・チャットの 1 行・通知から開く)。 一番上に操作者の原文を枠で囲んで固定し、 下に件を時刻の順に出し、
// 一番下の欄は票の今で変わる (= TicketLower)。 別の機械の票は開かない (= 一覧の数だけ。 backend が `ticket_elsewhere` で断る)。

export default function TicketView() {
  const t = useT()
  const ticketId = useSyncExternalStore(subscribeUi, getUiSnapshot).overlays.ticket
  const { sessions } = useSyncExternalStore(subscribeSessions, getSessionsSnapshot)
  const { tickets } = useSyncExternalStore(subscribeTickets, getTicketsSnapshot)
  const summary = useMemo(() => tickets.find((ticket) => ticket.id === ticketId) || null, [tickets, ticketId])
  const { detail, error, reload } = useTicketDetail(ticketId, summary)

  const tabNames = useMemo(() => Object.fromEntries(sessions.map((s) => [s.id, s.title])), [sessions])
  const candidates = useMemo(() => sessions.filter((s) => !isApiTab(s)).map((s) => ({ id: s.id, title: s.title })), [sessions])
  const onClose = () => setOverlay('ticket', null)
  useEscape(onClose)

  const operatorLine = detail?.entries.find((entry) => entry.kind === 'operator') || null
  const entries = detail ? detail.entries.filter((entry) => entry !== operatorLine) : []
  const heading = summary ? ticketLabel(summary) : (detail?.entries.find((entry) => entry.title)?.title || ticketId)

  return (
    <div className="modal-overlay modal-overlay-preview ticket-overlay" onClick={onClose} data-testid="ticket-view">
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <span className="modal-path ticket-heading" data-testid="ticket-heading">📌 {heading}</span>
          <div className="modal-actions">
            <button className="modal-close" onClick={onClose} aria-label={t('common.close')} data-testid="ticket-close">✕</button>
          </div>
        </div>
        <div className="modal-body ticket-body">
          {error && <span className="error" data-testid="ticket-load-error">{error.message || t('ticket.load_error')}</span>}
          {!detail && !error && <span className="dim">{t('ticket.loading')}</span>}
          {operatorLine && (
            <blockquote className="ticket-original" data-testid="ticket-original">
              <span className="ticket-original-label">{t('ticket.original')}</span>
              <div className="ticket-original-text">{operatorLine.text}</div>
            </blockquote>
          )}
          {detail && <TicketEntries entries={entries} tabNames={tabNames} />}
        </div>
        {detail && <TicketLower ticketId={ticketId} detail={detail} candidates={candidates} reload={reload} />}
      </div>
    </div>
  )
}
