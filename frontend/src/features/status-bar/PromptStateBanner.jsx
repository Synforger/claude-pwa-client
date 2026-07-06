import { useEffect, useState, useSyncExternalStore } from 'react'
import { useT } from '../../i18n/t.js'
import {
  getSnapshot as getPromptSnapshot,
  selectFor,
  subscribe as subscribePrompt,
} from '../../state/promptState.js'
import { PromptReplyControls } from './PromptReplyControls.jsx'
import './PromptStateBanner.css'

// tmux pane が「入力待ち」 のとき、 チャット入力欄の直上に出す banner (= 2026-07-05
// StatusBar chip から移設)。 StatusBar は縦幅 1 行で狭く、 スマホでは chip が PR
// chip を押し出す + 「チャットに出す」 という UI 合意にも反していた。
//
// 表示条件: 待ち系 state (= tui / inline_tui / text_prompt) のみ。 idle は出さない
// (= ノイズ、 沈黙は ActivityBar の役割)。 bypass 表示も廃止 (= status 情報は
// Claude Code 自身の pane にあり、 banner は「今すぐ答えられる」 に集中)。

const BANNER_LABELS = {
  text_prompt: { icon: '⏸', label: 'Terminal is waiting for input' },
  inline_tui: { icon: '⌨', label: 'Selection prompt' },
  tui: { icon: '⌨', label: 'TUI running — use terminal view' },
}

// tui は「TUI_CONFIRM_MS 継続して観測されたら表示」 (= 確定待ち)。 読み込み / SSE 再接続の
// 初回 snapshot や poll の瞬間的な alternate_on 誤観測で一発 tui が来ても、 次 poll
// (500ms) の復帰遷移が先に届けば banner は一度も出ない。 text_prompt / inline_tui は
// quick-reply の即答性が価値なので確定待ちを掛けない (= 誤検知報告も tui のみ)。
export const TUI_CONFIRM_MS = 700

// entry が tui の間、 「tui へ遷移してから TUI_CONFIRM_MS 経過したか」 を返す hook。
// effect の deps は tui か否かだけ (= tui 継続中の excerpt 変化 publish では timer を
// 張り直さない = banner が点滅しない)。 tui を抜けたら即リセット、 再突入で再度確定待ち。
function useTuiConfirmed(sid, entry) {
  const isTui = !!entry && entry.state === 'tui'
  const [confirmed, setConfirmed] = useState(false)
  useEffect(() => {
    if (!isTui) {
      setConfirmed(false)
      return undefined
    }
    const timer = setTimeout(() => setConfirmed(true), TUI_CONFIRM_MS)
    return () => clearTimeout(timer)
  }, [sid, isTui])
  return !isTui || confirmed
}

export function PromptStateBanner({ sid }) {
  const t = useT()
  const snapshot = useSyncExternalStore(subscribePrompt, getPromptSnapshot)
  const entry = selectFor(snapshot, sid)
  const confirmed = useTuiConfirmed(sid, entry)
  if (!entry) return null
  const shape = BANNER_LABELS[entry.state]
  if (!shape) return null
  if (!confirmed) return null

  // 全文表示 (= 切らない)。 高さは CSS max-height + scroll で制御する。
  // Type something 選択中の表示切替は controls 側が excerpt から自律判定する
  // (= excerpt は残す: pane の実況 = 入力行にカーソルが居るのが見えてる方が分かりやすい)。
  const excerpt = entry.excerpt || ''

  return (
    <div className="prompt-banner" data-testid="prompt-state-banner">
      <div className="prompt-banner-head">
        <span className="prompt-banner-icon">{shape.icon}</span>
        <span className="prompt-banner-label">{shape.label}</span>
      </div>
      {excerpt ? (
        <pre className="prompt-banner-excerpt">{excerpt}</pre>
      ) : null}
      <PromptReplyControls sid={sid} entry={entry} />
      {/* 自由記述の導線: dialog が text 待ちの時も選択肢の "Other" 系でも、 通常の
          チャット送信 (= C-u wipe → paste → Enter) がそのまま dialog に刺さる。 専用
          入力欄は作らず既存の 1 入力欄に寄せる (= AskUserQuestion UI 統合の設計判断)。 */}
      {entry.inputMode !== 'none' && (
        <div className="prompt-banner-hint">{t('prompt.free_text_hint')}</div>
      )}
    </div>
  )
}
