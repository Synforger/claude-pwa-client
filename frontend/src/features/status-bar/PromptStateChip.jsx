import { useSyncExternalStore } from 'react'
import {
  getSnapshot as getPromptSnapshot,
  selectFor,
  subscribe as subscribePrompt,
} from '../../state/promptState.js'

// tmux pane が入力待ち (= subprocess prompt / TUI 選択肢 / 長時間 idle) に落ちたら
// StatusBar に chip を差し込む。 表示は 4 段階:
//
//   text_prompt   ⏸ waiting: <excerpt>          — sudo / ssh / [Y/n] / OTP など
//   inline_tui    ⌨ selection: <excerpt>        — Inquirer / Claude Code 選択 dialog
//   tui           ⌨ TUI running                — less / vim / fzf / $EDITOR
//   idle          ⋯ idle                        — 長時間沈黙 (= 出力停止)
//
// active state は何も出さない (= 通常動作なので UI を汚さない)。
// bypass mode chip は独立表示 (= 表示中は「Claude Code 側は自動許可、 でも subprocess
// prompt は素通り」 の警戒として意味を持つ)。

const PROMPT_LABELS = {
  text_prompt: (excerpt) => ({ icon: '⏸', label: 'waiting', detail: excerpt }),
  inline_tui: (excerpt) => ({ icon: '⌨', label: 'selection', detail: excerpt }),
  tui: () => ({ icon: '⌨', label: 'TUI running', detail: '' }),
  idle: () => ({ icon: '⋯', label: 'idle', detail: '' }),
}

function truncate(text, max = 60) {
  if (!text) return ''
  const oneLine = text.replace(/\s+/g, ' ').trim()
  return oneLine.length <= max ? oneLine : oneLine.slice(0, max - 1) + '…'
}

export function PromptStateChip({ sid }) {
  const snapshot = useSyncExternalStore(subscribePrompt, getPromptSnapshot)
  const entry = selectFor(snapshot, sid)
  if (!entry) return null

  const chips = []

  // bypass mode chip: 「Claude Code の permission dialog 自動 yes、 subprocess prompt は
  // 素通り」 の状態。 検出中は常時 chip を出す (= ユーザに意識させる)。
  if (entry.bypassModeVisible) {
    chips.push(
      <span
        key="bypass"
        className="prompt-chip bypass"
        title="Claude Code is in bypass-permissions mode; subprocess prompts still stall."
        data-testid="prompt-state-bypass-chip"
      >
        ⏵⏵ bypass
      </span>
    )
  }

  const shape = PROMPT_LABELS[entry.state]
  if (shape) {
    const { icon, label, detail } = shape(entry.excerpt)
    const title = detail
      ? `${label}: ${entry.excerpt}`
      : `${label} (${entry.reason || 'no detail'})`
    chips.push(
      <span
        key="state"
        className={`prompt-chip prompt-state-${entry.state}`}
        title={title}
        data-testid="prompt-state-chip"
      >
        {icon} {label}
        {detail ? <span className="prompt-chip-detail">: {truncate(detail)}</span> : null}
      </span>
    )
  }

  return chips.length ? <>{chips}</> : null
}
