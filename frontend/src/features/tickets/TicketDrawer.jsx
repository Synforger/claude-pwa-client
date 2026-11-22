import { useEffect, useMemo, useState, useSyncExternalStore } from 'react'
import { useT } from '../../i18n/t.js'
import { setOverlay, subscribe as subscribeUi, getSnapshot as getUiSnapshot } from '../../state/ui.js'
import { subscribe as subscribeSessions, getSnapshot as getSessionsSnapshot, selectTab } from '../../state/sessions.js'
import { subscribe as subscribeTickets, getSnapshot as getTicketsSnapshot } from '../../state/tickets.js'
import { useEscape } from '../../_common/useEscape.js'
import '../../_common/Modal.css'
import './Tickets.css'
import { OPEN_GROUPS, agoOf, holderOf, markOf, peerLines, ticketLabel, ticketSections } from './ticketGroups.js'

// 票の一覧 (= 帯の 🎫 から開く)。 上に今のタブの票、 下にほかの票をタブごとに出す。 それぞれ「見てほしい」「動いている」「待ち」 の段で、 「閉じた」 (畳む) は
// 全部のタブの分を最後に 1 段。 票の行を押すと票の画面、 タブの見出しを押すとそのタブへ移る。
// A row shows the next step its tab last wrote (when there is one), the due date (when there is one) and the first mark as one character.
// 一番下に、 もう 1 台の機械で操作者の答えを待つ票の数 (= その機械の画面で答える)。

const NOW_TICK_MS = 30_000

function useNow() {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), NOW_TICK_MS)
    return () => clearInterval(timer)
  }, [])
  return now
}

function holderName(id, tabNames, t) {
  const holder = holderOf(id)
  if (holder.kind === 'none') return t('tickets.holder_none')
  if (holder.kind === 'machine') return t('tickets.holder_machine', { machine: holder.machine })
  return tabNames[holder.id] || holder.id
}

// `holderText` only where no heading above the row names the tab
function Row({ ticket, holderText = null, now, t }) {
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
        {holderText && <span className="ticket-row-holder">{holderText}</span>}
        {ticket.due && <span className={`ticket-row-due${mark?.key === 'overdue' ? ' ticket-row-due-overdue' : ''}`} data-testid="ticket-row-due">{t('tickets.due', { date: ticket.due })}</span>}
        {ago && <span className="ticket-row-ago">{t(`tickets.ago_${ago.unit}`, { count: ago.count })}</span>}
      </span>
      {ticket.attention === 'delivery' && <span className="ticket-row-problem">{t('tickets.row_delivery')}</span>}
    </button>
  )
}

function OpenGroups({ groups, now, t }) {
  return OPEN_GROUPS.filter((group) => groups[group].length > 0).map((group) => (
    <section key={group} className="ticket-group" data-testid={`ticket-group-${group}`}>
      <div className="ticket-group-title">{t(`tickets.group_${group}`)} ({groups[group].length})</div>
      {groups[group].map((ticket) => <Row key={ticket.id} ticket={ticket} now={now} t={t} />)}
    </section>
  ))
}

export default function TicketDrawer() {
  const t = useT()
  const { tickets, peers, loaded } = useSyncExternalStore(subscribeTickets, getTicketsSnapshot)
  const { sessions, activeId } = useSyncExternalStore(subscribeSessions, getSessionsSnapshot)
  const ui = useSyncExternalStore(subscribeUi, getUiSnapshot)
  const [closedOpen, setClosedOpen] = useState(false)
  const now = useNow()
  const { own, others, closed } = useMemo(() => ticketSections(tickets, activeId, now), [tickets, activeId, now])
  const tabNames = useMemo(() => Object.fromEntries(sessions.map((s) => [s.id, s.title])), [sessions])
  const lines = peerLines(peers)
  const onClose = () => setOverlay('tickets', false)
  const openTab = (sid) => { selectTab(sid); onClose() }
  // 票の画面が上に開いている間は、 Esc はそちらだけを閉じる
  const ticketOpen = !!ui.overlays.ticket
  useEscape(onClose, { enabled: !ticketOpen })

  return (
    <div className="modal-overlay modal-overlay-preview" onClick={onClose} data-testid="ticket-drawer">
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <span className="modal-path ticket-heading" data-testid="ticket-drawer-heading">
            🎫 {t('tickets.title')}
          </span>
          <div className="modal-actions">
            <button className="modal-close" onClick={onClose} aria-label={t('common.close')} data-testid="ticket-drawer-close">✕</button>
          </div>
        </div>
        <div className="modal-body ticket-list">
          {!loaded && <span className="dim">{t('ticket.loading')}</span>}
          {loaded && tickets.length === 0 && <p className="dim">{t('tickets.empty')}</p>}
          {loaded && tickets.length > 0 && own && (
            <section className="ticket-section" data-testid="ticket-section-own">
              <div className="ticket-section-title">{t('tickets.section_own')}</div>
              {OPEN_GROUPS.every((group) => own[group].length === 0) && <span className="dim">{t('tickets.empty')}</span>}
              <OpenGroups groups={own} now={now} t={t} />
            </section>
          )}
          {others.length > 0 && (
            <section className="ticket-section" data-testid="ticket-section-others">
              <div className="ticket-section-title">{t(own ? 'tickets.section_others' : 'tickets.section_all')}</div>
              {others.map(({ holder, groups }) => (
                <section key={holder} className="ticket-holder" data-testid="ticket-holder" data-holder={holder}>
                  {Object.hasOwn(tabNames, holder) ? (
                    <button type="button" className="ticket-holder-title ticket-holder-open" onClick={() => openTab(holder)} title={t('tickets.open_tab')} data-testid="ticket-holder-open">
                      {holderName(holder, tabNames, t)} ›
                    </button>
                  ) : (
                    <div className="ticket-holder-title">{holderName(holder, tabNames, t)}</div>
                  )}
                  <OpenGroups groups={groups} now={now} t={t} />
                </section>
              ))}
            </section>
          )}
          {closed.length > 0 && (
            <section className="ticket-group" data-testid="ticket-group-closed">
              <button type="button" className="ticket-group-title ticket-group-toggle" onClick={() => setClosedOpen(!closedOpen)} data-testid="ticket-group-toggle">
                {closedOpen ? '▾' : '▸'} {t('tickets.group_closed')} ({closed.length})
              </button>
              {closedOpen && closed.map((ticket) => <Row key={ticket.id} ticket={ticket} holderText={holderName(ticket.holder, tabNames, t)} now={now} t={t} />)}
            </section>
          )}
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
