import { useSyncExternalStore } from 'react'
import { useT } from '../../i18n/t.js'
import {
  getSnapshot as getPromptSnapshot,
  selectFor,
  selectTypingAnswer,
  setTypingAnswer,
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

export function PromptStateBanner({ sid, answerPending = false }) {
  const t = useT()
  const snapshot = useSyncExternalStore(subscribePrompt, getPromptSnapshot)
  const entry = selectFor(snapshot, sid)
  const typing = selectTypingAnswer(snapshot, sid)
  if (!entry) return null
  const shape = BANNER_LABELS[entry.state]
  if (!shape) return null

  // Type something 選択後の「回答入力中」 mode: 数字ボタン / excerpt を出さない
  // (= pane にはまだ選択肢が見えたままなので、 ボタンを残すと数字タップが text 入力に
  // 化ける)。 回答はチャット入力欄から。 「選択肢を再表示」 で手動復帰もできる。
  if (typing) {
    return (
      <div className="prompt-banner prompt-banner-typing" data-testid="prompt-state-banner">
        <div className="prompt-banner-head">
          <span className="prompt-banner-label">{t('prompt.typing_answer')}</span>
          <button
            type="button"
            className="prompt-banner-back"
            onClick={() => setTypingAnswer(sid, false)}
            data-testid="prompt-banner-show-options"
          >
            {t('prompt.show_options')}
          </button>
        </div>
      </div>
    )
  }

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
      <PromptReplyControls sid={sid} entry={entry} answerPending={answerPending} />
      {/* 自由記述の導線: dialog が text 待ちの時も選択肢の "Other" 系でも、 通常の
          チャット送信 (= C-u wipe → paste → Enter) がそのまま dialog に刺さる。 専用
          入力欄は作らず既存の 1 入力欄に寄せる (= AskUserQuestion UI 統合の設計判断)。 */}
      {entry.inputMode !== 'none' && (
        <div className="prompt-banner-hint">{t('prompt.free_text_hint')}</div>
      )}
    </div>
  )
}
