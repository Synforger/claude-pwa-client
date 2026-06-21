import { useEffect, useRef, useState } from 'react'
import { pctClass, timeUntil, formatResetWeekdayTime } from '../utils/format.js'
import { useOutsideClick } from '../hooks/useOutsideClick.js'
import { useConnectionStatus } from '../hooks/useConnectionStatus.js'
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

// 「現在時刻 (秒)」 を 30 秒間隔で持つ。 hidden 中は止めて電力消費を抑え、 visible 復帰
// 時は即同期して古い数字を見せない。 旧 App.jsx で持っていた state を StatusBar 内に
// 閉じ込めた (= F-12)。
function useNowSec() {
  const [nowSec, setNowSec] = useState(() => Math.floor(Date.now() / 1000))
  useEffect(() => {
    let id = null
    const tick = () => setNowSec(Math.floor(Date.now() / 1000))
    const start = () => {
      if (id != null) return
      tick()
      id = setInterval(tick, 30000)
    }
    const stop = () => {
      if (id != null) { clearInterval(id); id = null }
    }
    const onVis = () => { document.hidden ? stop() : start() }
    if (typeof document === 'undefined') return undefined
    if (!document.hidden) start()
    document.addEventListener('visibilitychange', onVis)
    return () => { stop(); document.removeEventListener('visibilitychange', onVis) }
  }, [])
  return nowSec
}

export default function StatusBar({ status }) {
  const nowSec = useNowSec()
  const isOnline = useConnectionStatus()
  if (!status) {
    return (
      <div className="statusbar">
        <span className="dim">---</span>
        {!isOnline && <span className="offline-chip" title="サーバへの接続が切れています">⚠ オフライン</span>}
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
      {!isOnline && <span className="offline-chip" title="サーバへの接続が切れています">⚠ オフライン</span>}
    </div>
  )
}

// PR チップ + dropdown。 タブごとに status.pr_links を受け取り、 別タブ切替時は親から
// 新しい status が同期で渡るので flicker しない。 dropdown は閉じた状態がデフォ。
function PrLinksChip({ links }) {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)
  // outside-click / touchstart で閉じる集約 hook (= F-29)。 touchstart は別 hook 呼び。
  useOutsideClick(ref, () => setOpen(false), { enabled: open })
  useOutsideClick(ref, () => setOpen(false), { enabled: open, eventName: 'touchstart' })
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
