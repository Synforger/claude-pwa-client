// 票の一覧の分け方と、 一覧・タブの一覧が出す短い文字を作る純関数 (= 画面にも通信にも触れない)。
// 一覧の材料は backend の `tickets` channel の行で、 「見てほしい」 かは行の `attention` が持つ (= backend の判定が真値)。

/** 一覧の段。 上から出す順。 */
export const GROUPS = ['attention', 'running', 'closed']

const WAITING = 'waiting'
const CLOSED = 'closed'
const MINUTE_MS = 60_000
const HOUR_MS = 60 * MINUTE_MS
const DAY_MS = 24 * HOUR_MS
/** 閉じた票を一覧に出す期間 (= 最後の件がこれより古い閉じた票は出さない。 記録は消えない)。 */
export const CLOSED_SHOWN_DAYS = 7
const CLOSED_SHOWN_MS = CLOSED_SHOWN_DAYS * DAY_MS

const lastAtOf = (ticket) => ticket.last_at || ticket.opened_at || ''

/** 「見てほしい」 票の数 (= 📌 の数)。 */
export function attentionCount(tickets) {
  return tickets.filter((ticket) => ticket.attention != null).length
}

// 閉じた票を出すか: 最後の件 (無ければ開いた時刻) が `nowMs` から 7 日以内。 時刻が読めない票は出さない。
function isRecentlyClosed(ticket, nowMs) {
  const at = Date.parse(lastAtOf(ticket))
  return Number.isFinite(at) && nowMs - at <= CLOSED_SHOWN_MS
}

/** 票を 3 段に分ける (`nowMs` は今の時刻)。 閉じた票は 7 日以内の物だけを出す。 「見てほしい」 は返事待ちを先に、 どの段も最後の件が新しい順。 */
export function groupTickets(tickets, nowMs) {
  const groups = { attention: [], running: [], closed: [] }
  for (const ticket of tickets) {
    if (ticket.attention != null) groups.attention.push(ticket)
    else if (ticket.status === CLOSED) {
      if (isRecentlyClosed(ticket, nowMs)) groups.closed.push(ticket)
    } else groups.running.push(ticket)
  }
  const newestFirst = (a, b) => lastAtOf(b).localeCompare(lastAtOf(a)) || b.id.localeCompare(a.id)
  groups.attention.sort((a, b) => (Number(b.attention === WAITING) - Number(a.attention === WAITING)) || newestFirst(a, b))
  groups.running.sort(newestFirst)
  groups.closed.sort(newestFirst)
  return groups
}

/** 最後の件からの経過を `{ unit, count }` で返す (= unit は i18n の key の後ろ)。 時刻が読めなければ null。 */
export function agoOf(iso, nowMs) {
  const at = Date.parse(iso)
  if (!Number.isFinite(at)) return null
  const elapsed = Math.max(0, nowMs - at)
  if (elapsed < MINUTE_MS) return { unit: 'now', count: 0 }
  if (elapsed < HOUR_MS) return { unit: 'minutes', count: Math.floor(elapsed / MINUTE_MS) }
  if (elapsed < DAY_MS) return { unit: 'hours', count: Math.floor(elapsed / HOUR_MS) }
  return { unit: 'days', count: Math.floor(elapsed / DAY_MS) }
}

/** 持つタブの表し方: 持つタブが無い / 別の機械のタブ (`<機械>:<id>`) / この機械のタブ。 */
export function holderOf(holder) {
  if (!holder) return { kind: 'none' }
  const colon = holder.indexOf(':')
  if (colon > 0) return { kind: 'machine', machine: holder.slice(0, colon) }
  return { kind: 'tab', id: holder }
}

/** 票の呼び名 (= 題。 題が読めない票は id)。 */
export const ticketLabel = (ticket) => ticket.title || ticket.id

/** タブごとの、 そのタブが今持つ票 (= 閉じた票は持つとは言わない)。 `{ [タブの id]: [{ id, label }] }`。 */
export function heldByTab(tickets) {
  const held = {}
  for (const ticket of tickets) {
    if (ticket.status === CLOSED || !ticket.holder || holderOf(ticket.holder).kind !== 'tab') continue
    ;(held[ticket.holder] ||= []).push({ id: ticket.id, label: ticketLabel(ticket) })
  }
  return held
}

/** 一覧の最後の行の材料: 機械ごとに、 操作者の答えを待つ票の数 (`waiting`)、 読めない時は null。 待つ票が 0 の機械は出さない。 */
export function peerLines(peers) {
  return Object.keys(peers).sort().map((machine) => ({
    machine,
    waiting: peers[machine]?.unreadable ? null : (peers[machine]?.waiting ?? 0),
  })).filter((line) => line.waiting !== 0)
}
