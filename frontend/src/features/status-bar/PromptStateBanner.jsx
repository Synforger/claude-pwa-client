import { useSyncExternalStore } from 'react'
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

export function PromptStateBanner({ sid }) {
  const snapshot = useSyncExternalStore(subscribePrompt, getPromptSnapshot)
  const entry = selectFor(snapshot, sid)
  if (!entry) return null
  const shape = BANNER_LABELS[entry.state]
  if (!shape) return null

  // 全文表示 (= 切らない)。 高さは CSS max-height + scroll で制御する。
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
    </div>
  )
}
