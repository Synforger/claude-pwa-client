// 設定の画面の入力 (= 文字列の欄) を、 PUT /settings に送る差分に変える純粋な部品と、 表示用の整形。
//
// 欄は文字列で持つ (= 入力途中の「7」「70」「」 をそのまま出す)。 空の欄は「その欄を消す」 (= 曜日の線なし、
// 眠らない、 既定に戻す) で、 差分では null になる。 書いた値が backend の規則 (= `backend/settings/settings_fields.py`)
// に合わない欄は invalid に名前で返し、 差分に入れない。 backend は同じ規則でもう一度確かめる。

export const WEEKDAYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']

// 7 日の枠が戻る日から数えた曜日の順 (= 線を上げた時に「後の曜日」 を決める順。 画面の並びは `WEEKDAYS` のまま)。
export const WEEK_FROM_SUNDAY = ['sun', 'mon', 'tue', 'wed', 'thu', 'fri', 'sat']

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

/** 口座の入力の初期値 (= view の今の値)。 days = 曜日ごとの線、 atPct = 逃げ先のある口座の 5 時間の線、
 *  ahead = その口座の先回りの幅、 fiveHour = 逃げ先のない口座の 5 時間の止める線 (= 空は線なし)。 */
export function accountDraftOf(account) {
  const fallback = account.mode === 'fallback'
  const table = fallback ? account.fallback.seven_day_at_pct : account.hold?.seven_day_at_pct
  return {
    atPct: fallback ? asText(account.fallback.at_pct) : '',
    ahead: fallback ? asText(account.fallback.ahead_pct) : '',
    fiveHour: fallback ? '' : asText(account.hold?.five_hour_at_pct),
    days: Object.fromEntries(WEEKDAYS.map((day) => [day, asText(table?.[day])])),
  }
}

/** 先回りの幅の欄の規則 (= 0 は先回りしない)。 */
export const aheadRule = (limits) => ({ min: limits.ahead_pct_min, max: limits.ahead_pct_max })

/** 口座の入力と今の値の差 → { patch, invalid }。 patch = PUT /settings の本文 (= 変わりが無ければ null)、
 *  invalid = 規則に合わない欄 (= 'atPct'・'ahead'・'fiveHour' と曜日の名前)。 */
export function accountPatch(account, draft, limits) {
  const range = lineRule(limits)
  const before = accountDraftOf(account)
  const invalid = []
  const fields = {}
  const days = {}
  if (account.mode === 'fallback') {
    const parsed = parseField(draft.atPct, range)
    if (!parsed.ok || parsed.value === null) invalid.push('atPct')
    else if (draft.atPct.trim() !== before.atPct) fields.at_pct = parsed.value
    const ahead = parseField(draft.ahead, aheadRule(limits))
    if (!ahead.ok) invalid.push('ahead')
    else if (draft.ahead.trim() !== before.ahead) fields.ahead_pct = ahead.value
  } else {
    const five = parseField(draft.fiveHour, range)
    if (!five.ok) invalid.push('fiveHour')
    else if (draft.fiveHour.trim() !== before.fiveHour) fields.five_hour_at_pct = five.value
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

/** ある曜日の線を書き換えた時に、 後の曜日の線を持ち上げる。 `days` = 曜日ごとの入力 (= 書き換えた後)、 `day` = 書き換えた
 *  曜日、 `before` = その欄の書き換える前の文字、 `range` = { min, max }。 → { days, lifted }。 lifted = 持ち上げた曜日。
 *  決まりは次だけで、 値を推測して動かさない:
 *   - 持ち上げるのは、 書き換えた曜日より後 (= `WEEK_FROM_SUNDAY` の順) で、 新しい値より低い線だけ。 新しい値まで上げる
 *   - 前の曜日は動かさない。 空の曜日 (= なし) と、 範囲外の文字が入った曜日は動かさない
 *   - 線を下げた時 (= 新しい値が前の値以下) と、 新しい値が空・範囲外の時は、 何も動かさない
 *   - 前の値が空だった欄に値を書いた時は、 下げたのではないので持ち上げる */
export function liftLaterDays(days, day, before, range) {
  const now = parseField(days[day], range)
  const was = parseField(before, range)
  if (!now.ok || now.value === null) return { days, lifted: [] }
  if (was.ok && was.value !== null && now.value <= was.value) return { days, lifted: [] }
  const lifted = []
  const next = { ...days }
  for (const later of WEEK_FROM_SUNDAY.slice(WEEK_FROM_SUNDAY.indexOf(day) + 1)) {
    const value = parseField(days[later], range)
    if (value.ok && value.value !== null && value.value < now.value) {
      next[later] = String(now.value)
      lifted.push(later)
    }
  }
  return lifted.length ? { days: next, lifted } : { days, lifted: [] }
}

/** エージェントの入力の初期値。 */
export function agentDraftOf(agent) {
  return {
    sleep: asText(agent.sleep_minutes),
    pressure: asText(agent.sleep_pressure_minutes),
    working: asText(agent.rollover.working_context_pct),
    idleContext: asText(agent.rollover.idle_context_pct),
    idleMinutes: asText(agent.rollover.idle_minutes),
  }
}

/** 口座の線の欄 (= 5 時間の線と曜日の線) の規則。 */
export const lineRule = (limits) => ({ min: limits.line_pct_min, max: limits.line_pct_max })

/** エージェントの欄ごとの規則 (= 入力の名前 → `parseField` の規則)。 */
export function agentRules(limits) {
  const pct = { min: limits.context_pct_min, max: limits.context_pct_max, whole: false }
  return {
    sleep: { min: limits.minutes_min },
    pressure: { min: limits.minutes_min },
    working: pct,
    idleContext: pct,
    idleMinutes: { min: limits.minutes_min, whole: false },
  }
}

/** 子のタブの上限の欄の規則。 */
export const CHILD_LIMIT_RULE = { min: 0 }

/** 規則に合わない時に欄の下へ出す理由の、 翻訳の key と値。 */
export function ruleMessage(rule) {
  const range = Number.isFinite(rule.max)
  const kind = rule.whole === false ? 'number' : 'whole'
  return { key: `settings.error.${kind}_${range ? 'range' : 'min'}`, vars: { min: rule.min, max: rule.max } }
}

/** エージェントの入力と今の値の差 → { patch, invalid }。 */
export function agentPatch(agent, draft, limits) {
  const before = agentDraftOf(agent)
  const rules = agentRules(limits)
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
  // 眠らない agent (= 分数を空にした) は、 逼迫の時の分数も外す。 残すと設定の検査が「眠らない agent の値」として断る
  const pressure = 'pressure' in value ? value.pressure
    : ('sleep' in value && value.sleep === null && before.pressure !== '' ? null : undefined)
  const sleep = {
    ...('sleep' in value ? { minutes: value.sleep } : {}),
    ...(pressure !== undefined ? { pressure_minutes: pressure } : {}),
  }
  const agentPatchBody = {
    ...(Object.keys(sleep).length ? { sleep } : {}),
    ...(Object.keys(rollover).length ? { rollover } : {}),
  }
  return { patch: { agents: { [agent.id]: agentPatchBody } }, invalid }
}

/** 子のタブの上限の入力 → { patch, invalid }。 空は上限なし (= null)。 */
export function childLimitPatch(currentValue, text) {
  const parsed = parseField(text, CHILD_LIMIT_RULE)
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

/** 使用率の横のバー。 `pct` = 使用率、 `resetsAt` = 窓が戻る時刻 (epoch 秒、 過ぎていれば使用率は古い値で 0 と読む)、
 *  `line` = 今日の線 (= 無ければ null)。 → { pct (0〜100 に収めた値)、 line、 over (= 線以上か) }。 */
export function usageBar({ pct, resetsAt, line, nowSeconds }) {
  const effective = hasReset(resetsAt, nowSeconds) || typeof pct !== 'number' ? 0 : pct
  const known = typeof line === 'number' ? line : null
  return { pct: Math.min(100, Math.max(0, effective)), line: known, over: known !== null && effective >= known }
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
