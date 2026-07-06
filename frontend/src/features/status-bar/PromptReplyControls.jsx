import { useState } from 'react'
import { apiFetch } from '../../utils/api.js'
import { setTypingAnswer } from '../../state/promptState.js'

// prompt_state.input_mode に応じた quick-reply UI (= Phase 4a)。
//
// pattern:
//   numbers → 検出 option digit ごとに button (= `1` `2` `3` `0`)。 Ink dialog は
//     enter 不要、 shell prompt (= bash select) は enter=true。
//   yn → `Y` / `n` button (= confirm_yn、 常に enter=true)
//   arrows → Phase 4b で実装。 4a ではボタン非表示。
//   none → null return (= chip だけ)
//
// tap したら POST /pty/{sid}/send-raw-key → backend が tmux に流す。 結果 chip は
// 次 poll (= 500ms) で state 遷移して自然に消える。

async function sendRawKey(sid, key, enter) {
  try {
    await apiFetch(`/pty/${encodeURIComponent(sid)}/send-raw-key`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ key, enter: !!enter }),
    })
  } catch { /* 送信失敗はサイレント (= 通常 chip が消えないだけ、 再 tap で復帰) */ }
}

export function PromptReplyControls({ sid, entry, answerPending = false }) {
  const [pending, setPending] = useState(false)
  if (!entry || !sid) return null
  const { inputMode, options, keyRequiresEnter } = entry
  if (inputMode !== 'numbers' && inputMode !== 'yn' && inputMode !== 'arrows') return null

  const handleTap = async (key, enterOverride) => {
    if (pending) return
    setPending(true)
    try {
      const enter = enterOverride !== undefined ? enterOverride : keyRequiresEnter
      await sendRawKey(sid, key, enter)
    } finally {
      // 短い timeout: 連打防止 + backend poll (= route の poke_now が 80ms 後に走る)
      // が新 excerpt を配って chip が自然更新される時間を稼ぐ。
      setTimeout(() => setPending(false), 250)
    }
  }

  // arrows mode = ↑↓ + ␣ + ⏎ の 4 button。 ␣ は番号なし checkbox 型 picker (= inquirer
  // checkbox 等、 カーソル行を Space で toggle する操作系) 用。 単一選択 picker では
  // 押しても無害。
  if (inputMode === 'arrows') {
    return (
      <span className="prompt-reply-controls" data-testid="prompt-reply-controls">
        <button
          type="button"
          className="prompt-reply-btn"
          disabled={pending}
          onClick={() => handleTap('Up', false)}
          aria-label="Move selection up"
          data-testid="prompt-reply-btn-up"
        >↑</button>
        <button
          type="button"
          className="prompt-reply-btn"
          disabled={pending}
          onClick={() => handleTap('Down', false)}
          aria-label="Move selection down"
          data-testid="prompt-reply-btn-down"
        >↓</button>
        <button
          type="button"
          className="prompt-reply-btn prompt-reply-btn-aux"
          disabled={pending}
          onClick={() => handleTap('Space', false)}
          aria-label="Toggle selection (multi-select)"
          data-testid="prompt-reply-btn-space"
        >␣</button>
        <button
          type="button"
          className="prompt-reply-btn"
          disabled={pending}
          onClick={() => handleTap('Enter', false)}
          aria-label="Confirm selection"
          data-testid="prompt-reply-btn-enter"
        >⏎</button>
      </span>
    )
  }

  const keys = inputMode === 'yn' ? ['Y', 'n'] : (options || [])
  if (keys.length === 0) return null

  return (
    <span className="prompt-reply-controls" data-testid="prompt-reply-controls">
      {keys.map((k, i) => (
        <button
          key={k}
          type="button"
          className="prompt-reply-btn"
          disabled={pending}
          onClick={() => {
            // 未回答の AskUserQuestion がある時、 最後の数字 = TUI が自動で足す
            // "Type something" (= 自由記述の入口)。 選んだ瞬間に banner を
            // 「回答入力中」 mode に切替える (= 以降の数字タップが text 入力に
            // 化ける事故を防ぐ、 2026-07-06 実害の再発防止)。
            if (answerPending && inputMode === 'numbers' && i === keys.length - 1) {
              setTypingAnswer(sid, true)
            }
            handleTap(k)
          }}
          aria-label={`Send ${k}`}
          data-testid={`prompt-reply-btn-${k}`}
        >
          {k}
        </button>
      ))}
      {/* multiSelect dialog (= AskUserQuestion の複数選択等) の確定用。 multi では数字
          キー自体が toggle として働く (= 2026-07-06 実機確認) ので Space は不要、 ⏎ だけ
          あればよい。 single select の Ink dialog は数字 1 打鍵で即決定するので押す必要
          なし (= 押しても害はない)。 */}
      {inputMode === 'numbers' && (
        <button
          type="button"
          className="prompt-reply-btn prompt-reply-btn-aux"
          disabled={pending}
          onClick={() => handleTap('Enter', false)}
          aria-label="Confirm selection"
          data-testid="prompt-reply-btn-confirm"
        >⏎</button>
      )}
    </span>
  )
}
