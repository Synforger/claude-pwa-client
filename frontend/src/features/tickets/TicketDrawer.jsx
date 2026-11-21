import { useEffect, useMemo, useState, useSyncExternalStore } from 'react'
import { useT } from '../../i18n/t.js'
import { setOverlay, subscribe as subscribeUi, getSnapshot as getUiSnapshot } from '../../state/ui.js'
import { subscribe as subscribeSessions, getSnapshot as getSessionsSnapshot } from '../../state/sessions.js'
import { subscribe as subscribeTickets, getSnapshot as getTicketsSnapshot } from '../../state/tickets.js'
import { useEscape } from '../../_common/useEscape.js'
import '../../_common/Modal.css'
import './Tickets.css'
import { GROUPS, agoOf, groupTickets, holderOf, markOf, peerLines, ticketLabel } from './ticketGroups.js'

// 票の一覧 (= 会話の一覧のいちばん上の 🎫 の行から開く。 タブの行の票の行から開いた時は、 そのタブが持つ票だけ)。 「見てほしい」「動いている」「待ち」「閉じた」 (畳む) の 4 段で、 行を押すと票の画面が開く。
// A row shows the next step its tab last wrote (when there is one), the due date (when there is one) and the first mark as one character.
// 一番下に、 もう 1 台の機械で操作者の答えを待つ票の数 (= その機械の画面で答える)。

const NOW_TICK_MS = 30_000
const CLOSED_GROUP = 'closed'

function useNow() {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), NOW_TICK_MS)
    return () => clearInterval(timer)
  }, [])
  return now
}

function Row({ ticket, tabNames, now, t }) {
  const holder = holderOf(ticket.holder)
  const holderText = holder.kind === 'none' ? t('tickets.holder_none')
    : holder.kind === 'machine' ? t('tickets.holder_machine', { machine: holder.machine })
      : (tabNames[holder.id] || holder.id)
  const ago = agoOf(ticket.last_at || ticket.opened_at || '', now)
  const wants = ticket.wants && ticket.status === 'waiting-operator' ? t(`tickets.wants_${ticket.wants}`) : null
  const mark = markOf(ticket)
  return (
    <button type="button" className="ticket-row" onClick={() => setOverlay('ticket', ticket.id)} data-testid="ticket-row" data-ticket={ticket.id}>
      <span className="ticket-row-title">{ticketLabel(ticket)}</span>
      {ticket.next && <span className="ticket-row-next" data-testid="ticket-row-next">{ticket.next}</span>}
      <span className="ticket-row-meta">
        {mark && <span className="ticket-row-mark" title={t(`tickets.mark_${mark.key}`)} aria-label={t(`tickets.mark_${mark.key}`)} data-testid="ticket-row-mark" data-mark={mark.key}>{mark.glyph}</span>}
        {wants && <span className="ticket-row-wants">{wants}</span>}
        <span className="ticket-row-holder">{holderText}</span>
        {ticket.due && <span className={`ticket-row-due${mark?.key === 'overdue' ? ' ticket-row-due-overdue' : ''}`} data-testid="ticket-row-due">{t('tickets.due', { date: ticket.due })}</span>}
        {ago && <span className="ticket-row-ago">{t(`tickets.ago_${ago.unit}`, { count: ago.count })}</span>}
      </span>
      {ticket.attention === 'delivery' && <span className="ticket-row-problem">{t('tickets.row_delivery')}</span>}
    </button>
  )
}

export default function TicketDrawer() {
  const t = useT()
  const { tickets: allTickets, peers, loaded } = useSyncExternalStore(subscribeTickets, getTicketsSnapshot)
  const { sessions } = useSyncExternalStore(subscribeSessions, getSessionsSnapshot)
  const ui = useSyncExternalStore(subscribeUi, getUiSnapshot)
  // 値がタブの id なら、 そのタブが持つ票だけ (= タブの行から開いた時)。 true なら全部
  const holderTab = typeof ui.overlays.tickets === 'string' ? ui.overlays.tickets : null
  const tickets = useMemo(() => (holderTab ? allTickets.filter((ticket) => ticket.holder === holderTab) : allTickets), [allTickets, holderTab])
  const [closedOpen, setClosedOpen] = useState(false)
  const now = useNow()
  const groups = useMemo(() => groupTickets(tickets, now), [tickets, now])
  const tabNames = useMemo(() => Object.fromEntries(sessions.map((s) => [s.id, s.title])), [sessions])
  const lines = holderTab ? [] : peerLines(peers)
  const onClose = () => setOverlay('tickets', false)
  // 票の画面が上に開いている間は、 Esc はそちらだけを閉じる
  const ticketOpen = !!ui.overlays.ticket
  useEscape(onClose, { enabled: !ticketOpen })

  return (
    <div className="modal-overlay modal-overlay-preview" onClick={onClose} data-testid="ticket-drawer">
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <span className="modal-path ticket-heading" data-testid="ticket-drawer-heading">
            🎫 {holderTab ? t('tickets.title_of_tab', { tab: tabNames[holderTab] || holderTab }) : t('tickets.title')}
          </span>
          <div className="modal-actions">
            <button className="modal-close" onClick={onClose} aria-label={t('common.close')} data-testid="ticket-drawer-close">✕</button>
          </div>
        </div>
        <div className="modal-body ticket-list">
          {!loaded && <span className="dim">{t('ticket.loading')}</span>}
          {loaded && tickets.length === 0 && <p className="dim">{t('tickets.empty')}</p>}
          {GROUPS.map((group) => {
            const rows = groups[group]
            if (rows.length === 0) return null
            const folded = group === CLOSED_GROUP && !closedOpen
            return (
              <section key={group} className="ticket-group" data-testid={`ticket-group-${group}`}>
                {group === CLOSED_GROUP ? (
                  <button type="button" className="ticket-group-title ticket-group-toggle" onClick={() => setClosedOpen(!closedOpen)} data-testid="ticket-group-toggle">
                    {folded ? '▸' : '▾'} {t(`tickets.group_${group}`)} ({rows.length})
                  </button>
                ) : (
                  <div className="ticket-group-title">{t(`tickets.group_${group}`)} ({rows.length})</div>
                )}
                {!folded && rows.map((ticket) => <Row key={ticket.id} ticket={ticket} tabNames={tabNames} now={now} t={t} />)}
              </section>
            )
          })}
          {lines.map((line) => (
            <div key={line.machine} className="ticket-peer" data-testid="ticket-peer">
              {line.waiting === null
                ? t('tickets.peer_unreadable', { machine: line.machine })
                : t('tickets.peer_waiting', { machine: line.machine, count: line.waiting })}
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
