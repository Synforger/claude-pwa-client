// 設定の画面の入力 (= 文字列の欄) を、 PUT /settings に送る差分に変える純粋な部品と、 表示用の整形。
//
// 欄は文字列で持つ (= 入力途中の「7」「70」「」 をそのまま出す)。 空の欄は「その欄を消す」 (= 曜日の線なし、
// 眠らない、 既定に戻す) で、 差分では null になる。 書いた値が backend の規則 (= `backend/settings/settings_fields.py`)
// に合わない欄は invalid に名前で返し、 差分に入れない。 backend は同じ規則でもう一度確かめる。

export const WEEKDAYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']

const WHOLE = /^\d+$/
const NUMBER = /^\d+(\.\d+)?$/

/** 入力の文字列 → { ok, value }。 空は value = null (= 消す)。 範囲 [min, max] の外と、 `whole` で小数は ok = false。 */
export function parseField(text, { min, max = Infinity, whole = true }) {
  const trimmed = String(text ?? '').trim()
  if (trimmed === '') return { ok: true, value: null }
  if (!(whole ? WHOLE : NUMBER).test(trimmed)) return { ok: false, value: null }
  const value = Number(trimmed)
  return value >= min && value <= max ? { ok: true, value } : { ok: false, value: null }
}

const asText = (value) => (value === null || value === undefined ? '' : String(value))

/** 口座の入力の初期値 (= view の今の値)。 days = 曜日ごとの線、 atPct = 5 時間の線 (= 逃げ先のある口座だけ)。 */
export function accountDraftOf(account) {
  const table = account.mode === 'fallback' ? account.fallback.seven_day_at_pct : account.hold?.seven_day_at_pct
  return {
    atPct: account.mode === 'fallback' ? asText(account.fallback.at_pct) : '',
    days: Object.fromEntries(WEEKDAYS.map((day) => [day, asText(table?.[day])])),
  }
}

/** 口座の入力と今の値の差 → { patch, invalid }。 patch = PUT /settings の本文 (= 変わりが無ければ null)、
 *  invalid = 規則に合わない欄 (= 'atPct' と曜日の名前)。 */
export function accountPatch(account, draft, limits) {
  const range = { min: limits.line_pct_min, max: limits.line_pct_max }
  const before = accountDraftOf(account)
  const invalid = []
  const fields = {}
  const days = {}
  if (account.mode === 'fallback') {
    const parsed = parseField(draft.atPct, range)
    if (!parsed.ok || parsed.value === null) invalid.push('atPct')
    else if (draft.atPct.trim() !== before.atPct) fields.at_pct = parsed.value
  }
  for (const day of WEEKDAYS) {
    const parsed = parseField(draft.days[day], range)
    if (!parsed.ok) invalid.push(day)
    else if (draft.days[day].trim() !== before.days[day]) days[day] = parsed.value
  }
  const key = account.mode === 'fallback' ? 'fallback' : 'hold'
  const section = { ...fields, ...(Object.keys(days).length ? { seven_day_at_pct: days } : {}) }
  if (invalid.length || !Object.keys(section).length) return { patch: null, invalid }
  return { patch: { accounts: { [account.id]: { [key]: section } } }, invalid }
}

/** エージェントの入力の初期値。 */
export function agentDraftOf(agent) {
  return {
    sleep: asText(agent.sleep_minutes),
    working: asText(agent.rollover.working_context_pct),
    idleContext: asText(agent.rollover.idle_context_pct),
    idleMinutes: asText(agent.rollover.idle_minutes),
  }
}

/** エージェントの入力と今の値の差 → { patch, invalid }。 */
export function agentPatch(agent, draft, limits) {
  const before = agentDraftOf(agent)
  const pct = { min: limits.context_pct_min, max: limits.context_pct_max, whole: false }
  const rules = {
    sleep: { min: limits.minutes_min },
    working: pct,
    idleContext: pct,
    idleMinutes: { min: limits.minutes_min, whole: false },
  }
  const invalid = []
  const value = {}
  for (const [name, rule] of Object.entries(rules)) {
    const parsed = parseField(draft[name], rule)
    if (!parsed.ok) invalid.push(name)
    else if (draft[name].trim() !== before[name]) value[name] = parsed.value
  }
  if (invalid.length || !Object.keys(value).length) return { patch: null, invalid }
  const rollover = {}
  if ('working' in value) rollover.working = { context_pct: value.working }
  if ('idleContext' in value || 'idleMinutes' in value) {
    rollover.idle = {
      ...('idleContext' in value ? { context_pct: value.idleContext } : {}),
      ...('idleMinutes' in value ? { minutes: value.idleMinutes } : {}),
    }
  }
  const agentPatchBody = {
    ...('sleep' in value ? { sleep: { minutes: value.sleep } } : {}),
    ...(Object.keys(rollover).length ? { rollover } : {}),
  }
  return { patch: { agents: { [agent.id]: agentPatchBody } }, invalid }
}

/** 子のタブの上限の入力 → { patch, invalid }。 空は既定に戻す (= null)。 */
export function childLimitPatch(currentValue, text) {
  const parsed = parseField(text, { min: 0 })
  if (!parsed.ok) return { patch: null, invalid: ['childSessionsMax'] }
  if (text.trim() === asText(currentValue)) return { patch: null, invalid: [] }
  return { patch: { child_sessions_max: parsed.value }, invalid: [] }
}

/** 通知の題の入力 → { patch }。 空は既定に戻す (= null)。 */
export function titlePatch(currentValue, text) {
  const trimmed = text.trim()
  if (trimmed === asText(currentValue)) return { patch: null }
  return { patch: { notification_title: trimmed === '' ? null : trimmed } }
}

/** 使用率の表示。 無い時は「—」。 */
export function formatPct(value) {
  return typeof value === 'number' ? `${Math.round(value)}%` : '—'
}

const two = (n) => String(n).padStart(2, '0')

/** epoch 秒 → 「月/日 時:分」 (= 端末の地方時)。 無い時は「—」。 */
export function formatMoment(epochSeconds) {
  if (typeof epochSeconds !== 'number') return '—'
  const at = new Date(epochSeconds * 1000)
  return `${at.getMonth() + 1}/${at.getDate()} ${two(at.getHours())}:${two(at.getMinutes())}`
}

/** 窓がもう戻っている (= `*_resets_at` が過ぎている) か。 戻っていれば使用率は古い値で、 0 と読む手がかりになる。 */
export function hasReset(epochSeconds, nowSeconds) {
  return typeof epochSeconds === 'number' && epochSeconds <= nowSeconds
}

/** 今日の曜日の名前 (= `WEEKDAYS` の 1 つ。 月曜が先頭)。 */
export function todayKey(date = new Date()) {
  return WEEKDAYS[(date.getDay() + 6) % 7]
}

/** backend の 400 の本文から、 断られた欄と理由の行を取り出す。 形が違えば detail の文をそのまま返す。 */
export function reasonsOf(body) {
  const detail = body?.detail
  const reasons = detail?.params?.reasons
  if (Array.isArray(reasons) && reasons.length) return reasons.map(String)
  if (typeof detail === 'string') return [detail]
  if (typeof detail?.message === 'string') return [detail.message]
  return []
}
