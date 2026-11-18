// API tabs: tabs with no Claude Code behind them (a program outside the client calls the Messages API and writes the
// conversation to a record the client only shows, `docs/reference/api-tabs.md`). What the screen asks about them lives
// here so every part answers it the same way: whether a tab is one, and how the context amount and the spend read.

/** The `kind` the backend gives the rows of an API tab (a Claude tab's row has none). */
export const API_KIND = 'api'

/** Every API tab id starts with this (= `backend/api_tabs/api_tab_table.py API_TAB_ID_PREFIX`). */
const API_TAB_ID_PREFIX = 'api_'

/** @param {{kind?: string}|null|undefined} session a row of the list
 *  @returns {boolean} whether the row is an API tab */
export function isApiTab(session) {
  return session?.kind === API_KIND
}

/** For the places that hold only a tab id (the unread marks, the loading flags).
 *  @param {string|null|undefined} sid
 *  @returns {boolean} */
export function isApiTabId(sid) {
  return typeof sid === 'string' && sid.startsWith(API_TAB_ID_PREFIX)
}

/** The context amount as the list and the bar show it: `950`, `12.3k`, `123.5k` (a thousand and over, one decimal).
 *  Nothing for an amount that is not known (= the tab has no answer with a `usage` yet; never 0).
 *  @param {number|null|undefined} tokens
 *  @returns {string|null} */
export function formatContextTokens(tokens) {
  if (typeof tokens !== 'number' || !Number.isFinite(tokens) || tokens < 0) return null
  if (tokens < 1000) return String(Math.round(tokens))
  return `${(tokens / 1000).toFixed(1)}k`
}

/** An amount of a wallet in its currency, without a currency sign that could be wrong for it: `1,234 JPY`.
 *  @param {number} amount
 *  @param {string} currency
 *  @returns {string} */
export function formatMoney(amount, currency) {
  const digits = Number.isInteger(amount) ? 0 : 2
  return `${amount.toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits })} ${currency}`
}

/** This month's spend of a wallet as one line: `123 / 1,000 JPY` (= spent / limit). Nothing when the wallet has no figure
 *  (the file is missing, broken or of another month: never 0).
 *  @param {{spent: number, limit: number, currency: string}|null|undefined} spend
 *  @returns {string|null} */
export function formatSpend(spend) {
  if (!spend || typeof spend.spent !== 'number' || typeof spend.limit !== 'number') return null
  const spent = spend.spent.toLocaleString('en-US', { maximumFractionDigits: 2 })
  return `${spent} / ${formatMoney(spend.limit, spend.currency)}`
}
