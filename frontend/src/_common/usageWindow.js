// The usage windows of an account (the 5 hours, the 7 days) as the screen reads them, in one place: whether a window
// has a figure to show now, and whether the account has no 5-hour window at all (a plan with the 7 days alone).
// Used by the status bar and the settings screen. A figure that is not known is never shown as 0.

/** @param {number|null|undefined} pct
 *  @param {number|null|undefined} resetsAt epoch seconds; 0 or none = not known
 *  @param {number} nowSeconds
 *  @returns {boolean} whether the window has a figure and has not reset */
export function isWindowCurrent(pct, resetsAt, nowSeconds) {
  return typeof pct === 'number' && !(resetsAt > 0 && resetsAt <= nowSeconds)
}

/** A window that has only reset keeps its old figure, so it still counts as one the account has.
 *  @param {{five_hour_pct?: number|null, seven_day_pct?: number|null}|null|undefined} usage
 *  @returns {boolean} whether the usage is known and has no 5-hour window */
export function lacksFiveHourWindow(usage) {
  return typeof usage?.seven_day_pct === 'number' && typeof usage?.five_hour_pct !== 'number'
}
