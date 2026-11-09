// 設定の画面の試験で使う GET /settings の答えの見本 (= backend/tests/settings/conftest.py の設定と同じ形)。
export const LIMITS = {
  weekdays: ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'],
  line_pct_min: 1, line_pct_max: 100, ahead_pct_min: 0, ahead_pct_max: 50, context_pct_min: 1, context_pct_max: 100,
  minutes_min: 1,
}

export const WORK = {
  id: 'work', display_name: 'Work', is_default: false,
  usage: { five_hour_pct: 30, five_hour_resets_at: 2_000_000_000, seven_day_pct: 40, seven_day_resets_at: 2_000_100_000 },
  mode: 'fallback',
  fallback: { to: 'personal', to_display_name: '個人', at_pct: 95, ahead_pct: 0, seven_day_at_pct: { mon: 70 }, seven_day_today_pct: 95 },
  hold: null, held_count: 0, tabs: { total: 3, running: 2, pinned: 1, held: 0 }, can_continue: false, pinned_tabs: [{ id: 'ses_p', title: '要のタブ' }],
}

export const PERSONAL = {
  id: 'personal', display_name: '個人', is_default: true,
  usage: { five_hour_pct: 10, five_hour_resets_at: 2_000_000_000, seven_day_pct: 55, seven_day_resets_at: 2_000_100_000 },
  mode: 'hold', fallback: null, hold: { five_hour_at_pct: null, seven_day_at_pct: { mon: 70, sat: 100 }, today_pct: 70 },
  held_count: 2, tabs: { total: 4, running: 1, pinned: 0, held: 2 }, can_continue: true, pinned_tabs: [],
}

export const AGENT = {
  id: 'agent_a', display_name: 'Agent A', sleep_minutes: 60,
  rollover: { working_context_pct: 60, idle_context_pct: 40, idle_minutes: 50 },
}

export const VIEW = {
  accounts: [WORK, PERSONAL],
  agents: [AGENT, { id: 'agent_b', display_name: 'Agent B', sleep_minutes: null,
    rollover: { working_context_pct: null, idle_context_pct: null, idle_minutes: null } }],
  child_sessions_max: 5,
  notification_title: '通知',
  machine: { version: '1.11.1', backend_started_at: 1_900_000_000, loop_stall: null },
  limits: LIMITS,
}
