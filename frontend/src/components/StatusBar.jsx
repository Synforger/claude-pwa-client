import { useState, useEffect, useRef } from 'react'
import { pctClass, timeUntil, formatResetWeekdayTime } from '../utils/format.js'
import { apiFetch } from '../utils/api.js'
import './StatusBar.css'

// 7d window のリセットタイミング: Anthropic 仕様は **rolling 7-day window**
// (= 最初の prompt から 7 日)、 固定曜日 / 固定時刻ではない。 旧仕様コメント「毎週土曜
// 18:00 JST 固定」 は誤りだったので撤回 (2026-05-09)。 動的値 (= header から取った
// resets_at) が取れない時は label を出さない (= 嘘表示しない方針)。

// 上部のステータス行: モデル名 / 5h / 7d / ctx 使用率 (= 表示専用)。
// モデル名は長い (= 1M 等の context 表記が付く) と折り返すので CSS で省略する。
// resets_at が 0 (未知) の間は生の pct を信用、既知かつ過去なら「窓切れ = 0%」扱い。
// Model & Effort の変更入口は ⋯ メニューに一本化したので、 ここには pill を出さない
// (= 旧 effort / fast pill は撤去、 2026-05-29)。

// モデル表示名を「Tier Version [1M]」 の最小形に正規化する。 statusline は (a) 生 API id
// (= `claude-opus-4-8[1m]`、 [1m] 付きフル ID 指定時にフレンドリー名へ解決されない) や
// (b) `Opus 4.7 (1M context)` のような冗長名を返すので、 どちらも「Opus 4.8 1M」 /
// 「Haiku 4.5」 のように揃える (= モデル名 + バージョン + コンテキスト数字だけ)。
function cleanModel(m) {
  if (!m) return m
  const s = String(m).trim()
  const id = s.match(/claude-(opus|sonnet|haiku)-(\d+)-(\d+)(\[1m\])?/i)
  if (id) {
    const tier = id[1].charAt(0).toUpperCase() + id[1].slice(1).toLowerCase()
    return `${tier} ${id[2]}.${id[3]}${id[4] ? ' 1M' : ''}`
  }
  return s.replace(/\s*\(1M context\)/i, ' 1M').replace(/\s*\([^)]*\)/g, '').trim()
}

export default function StatusBar({ status, nowSec }) {
  if (!status) {
    return (
      <div className="statusbar">
        <span className="dim">---</span>
      </div>
    )
  }
  const expired = status.five_hour_resets_at > 0 && status.five_hour_resets_at < nowSec
  const fivePct = expired ? 0 : status.five_hour_pct
  // 7d リセット: backend が動的に取れた時 (resets_at > 0) はそれ、 取れない時は表示しない
  const sevenDayResetLabel = status.seven_day_resets_at > 0
    ? formatResetWeekdayTime(status.seven_day_resets_at)
    : ''
  const modeLabel = formatMode(status.mode)
  const budgetLabel = formatBudget(status)
  return (
    <div className="statusbar">
      <span className="model">{cleanModel(status.model)}</span>
      {modeLabel && <span className="mode-chip">{modeLabel}</span>}
      {budgetLabel && <span className="budget-chip">{budgetLabel}</span>}
      <span className={pctClass(fivePct)}>
        5h {Math.round(fivePct)}%{' '}
        <span className="dim">{timeUntil(status.five_hour_resets_at, nowSec)}</span>
      </span>
      <span className={pctClass(status.seven_day_pct)}>
        7d {Math.round(status.seven_day_pct)}%{' '}
        <span className="dim">{sevenDayResetLabel}</span>
      </span>
      <span className={pctClass(status.ctx_pct)}>ctx {Math.round(status.ctx_pct || 0)}%</span>
      <PrLinksChip links={Array.isArray(status.pr_links) ? status.pr_links : []} />
      <AccountChip />
    </div>
  )
}

// 個人 / 仕事 アカウント切替チップ。 タップ 1 つで keychain credentials を入れ替えて
// 全 tmux session を kill → autoresume で新アカウントの claude が既存 jsonl を再開する。
// 試作段階なので確認 dialog は出す。
function AccountChip() {
  const [profile, setProfile] = useState(null)
  const [busy, setBusy] = useState(false)
  const fetchState = () => {
    apiFetch('/account')
      .then(r => r.ok ? r.json() : Promise.reject())
      .then(d => setProfile(d.profile))
      .catch(() => { /* unauthenticated or no profiles */ })
  }
  useEffect(fetchState, [])
  if (!profile) return null
  const other = profile === 'personal' ? 'work' : 'personal'
  const onSwitch = async () => {
    if (busy) return
    if (!window.confirm(`Switch to ${other} account?\n(All running tabs will resume on the new credentials.)`)) return
    setBusy(true)
    try {
      const r = await apiFetch('/account/switch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ target: other }),
      })
      const d = await r.json().catch(() => ({}))
      if (d.changed) setProfile(d.profile)
      else fetchState()
    } finally {
      setBusy(false)
    }
  }
  return (
    <button
      type="button"
      className={`acct-chip acct-${profile} ${busy ? 'busy' : ''}`}
      onClick={onSwitch}
      title={`${profile} (tap to switch to ${other})`}
    >
      {profile === 'work' ? '🏢 work' : '👤 personal'}
    </button>
  )
}

// PR チップ + dropdown。 タブごとに status.pr_links を受け取り、 別タブ切替時は親から
// 新しい status が同期で渡るので flicker しない。 dropdown は閉じた状態がデフォ。
function PrLinksChip({ links }) {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)
  useEffect(() => {
    if (!open) return undefined
    const onDoc = (e) => {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false)
    }
    document.addEventListener('mousedown', onDoc)
    document.addEventListener('touchstart', onDoc)
    return () => {
      document.removeEventListener('mousedown', onDoc)
      document.removeEventListener('touchstart', onDoc)
    }
  }, [open])
  if (!links.length) return null
  return (
    <span className="pr-chip-wrap" ref={ref}>
      <button
        type="button"
        className="pr-chip"
        onClick={(e) => { e.stopPropagation(); setOpen(o => !o) }}
        aria-label={`PR 一覧 (${links.length})`}
      >
        🔗 {links.length}
      </button>
      {open && (
        <div className="pr-chip-dropdown" onClick={(e) => e.stopPropagation()}>
          {links.map(l => (
            <a
              key={`${l.prRepository}#${l.prNumber}`}
              href={l.prUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="pr-chip-item"
            >
              <span className="pr-chip-num">#{l.prNumber}</span>
              <span className="pr-chip-repo">{l.prRepository}</span>
            </a>
          ))}
        </div>
      )}
    </span>
  )
}

function formatMode(m) {
  if (!m || m === 'normal') return null
  if (m === 'plan') return 'plan'
  return m
}

function formatBudget(s) {
  const rem = s.budget_remaining
  const total = s.budget_total
  if (rem == null || total == null) return null
  const fmt = (n) => typeof n === 'number' ? (n < 10 ? n.toFixed(2) : n.toFixed(0)) : String(n)
  return `$${fmt(rem)}/${fmt(total)}`
}
