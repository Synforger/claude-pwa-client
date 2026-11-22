// 票の一覧の分け方と、 一覧・会話の一覧の 🎫 の行・帯の 🎫 が出す数と短い文字を作る純関数 (= 画面にも通信にも触れない)。
// 一覧の材料は backend の `tickets` channel の行で、 「見てほしい」 かは行の `attention`、 印は行の `marks` が持つ (= backend の判定が真値)。

/** 一覧の段。 上から出す順。 */
export const GROUPS = ['attention', 'running', 'waiting', 'closed']

const ATTENTION_WAITING = 'waiting'
const STATUS_WAITING = 'waiting'
const CLOSED = 'closed'
// The one character a row shows for a mark. `marks` arrives in the order of priority and the first known one is shown.
// The warning sign carries U+FE0F so it is drawn as an emoji, like the others (without it it is drawn small and pale).
const MARK_GLYPHS = { overdue: '⚠\uFE0F', due_soon: '⏰', waiting_stale: '💤', idle: '💤' }
const MINUTE_MS = 60_000
const HOUR_MS = 60 * MINUTE_MS
const DAY_MS = 24 * HOUR_MS
/** 閉じた票を一覧に出す期間 (= 最後の件がこれより古い閉じた票は出さない。 記録は消えない)。 */
export const CLOSED_SHOWN_DAYS = 7
const CLOSED_SHOWN_MS = CLOSED_SHOWN_DAYS * DAY_MS

const lastAtOf = (ticket) => ticket.last_at || ticket.opened_at || ''

/** 操作者が動く票か: 答えを待つ・届かなかった答え・持つタブが無い (= backend の `attention`) か、 期限を過ぎた。
 * タブどうしの頼みで動いている票は入らない (= 票の一覧の「動いている」「待ち」 の段で見る)。 */
export function needsOperator(ticket) {
  return ticket.attention != null || (Array.isArray(ticket.marks) && ticket.marks.includes('overdue'))
}

/** 「見てほしい」 票の数 (= 会話の一覧の 🎫 の行と、 帯の 🎫 の数)。 操作者が動く票だけを数える。 */
export function attentionCount(tickets) {
  return tickets.filter(needsOperator).length
}

/** The two numbers of 🎫: what the operator acts on among the tickets the tab `tabId` holds, and among all. */
export function attentionCounts(tickets, tabId) {
  return { own: attentionCount(tickets.filter((ticket) => ticket.holder === tabId)), total: attentionCount(tickets) }
}

// 閉じた票を出すか: 最後の件 (無ければ開いた時刻) が `nowMs` から 7 日以内。 時刻が読めない票は出さない。
function isRecentlyClosed(ticket, nowMs) {
  const at = Date.parse(lastAtOf(ticket))
  return Number.isFinite(at) && nowMs - at <= CLOSED_SHOWN_MS
}

/** Sorts the tickets into the four groups (`nowMs` is now). A `waiting` ticket goes to the waiting group; a closed ticket shows only within 7 days. In every group the newest comes first, and in the first group the ones that wait for the operator's answer come before the others. */
export function groupTickets(tickets, nowMs) {
  const groups = { attention: [], running: [], waiting: [], closed: [] }
  for (const ticket of tickets) {
    if (needsOperator(ticket)) groups.attention.push(ticket)
    else if (ticket.status === CLOSED) {
      if (isRecentlyClosed(ticket, nowMs)) groups.closed.push(ticket)
    } else if (ticket.status === STATUS_WAITING) groups.waiting.push(ticket)
    else groups.running.push(ticket)
  }
  const newestFirst = (a, b) => lastAtOf(b).localeCompare(lastAtOf(a)) || b.id.localeCompare(a.id)
  groups.attention.sort((a, b) => (Number(b.attention === ATTENTION_WAITING) - Number(a.attention === ATTENTION_WAITING)) || newestFirst(a, b))
  for (const group of ['running', 'waiting', 'closed']) groups[group].sort(newestFirst)
  return groups
}

/** The mark a row shows: the first known one of `marks` as `{ key, glyph }` (`key` is the end of its i18n key), or null when there is none. */
export function markOf(ticket) {
  const key = (Array.isArray(ticket.marks) ? ticket.marks : []).find((mark) => Object.hasOwn(MARK_GLYPHS, mark))
  return key ? { key, glyph: MARK_GLYPHS[key] } : null
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

/** What the head of the ticket screen shows: the state (the end of its i18n key), whether the operator asked for it, and the due date (null when none). */
export function factsOf(ticket) {
  return { status: String(ticket.status || '').replaceAll('-', '_'), fromOperator: ticket.origin === 'operator', due: ticket.due || null }
}

/** 一覧の最後の行の材料: 機械ごとに、 操作者の答えを待つ票の数 (`waiting`)、 読めない時は null。 待つ票が 0 の機械は出さない。 */
export function peerLines(peers) {
  return Object.keys(peers).sort().map((machine) => ({
    machine,
    waiting: peers[machine]?.unreadable ? null : (peers[machine]?.waiting ?? 0),
  })).filter((line) => line.waiting !== 0)
}
