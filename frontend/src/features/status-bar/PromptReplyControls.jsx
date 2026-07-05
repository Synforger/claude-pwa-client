import { useState } from 'react'
import { apiFetch } from '../../utils/api.js'

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

export function PromptReplyControls({ sid, entry }) {
  const [pending, setPending] = useState(false)
  if (!entry || !sid) return null
  const { inputMode, options, keyRequiresEnter } = entry
  if (inputMode !== 'numbers' && inputMode !== 'yn') return null

  const handleTap = async (key) => {
    if (pending) return
    setPending(true)
    try {
      await sendRawKey(sid, key, keyRequiresEnter)
    } finally {
      // 短い timeout: 連打防止 + backend poll (500ms) が新 state を配って chip が
      // 自然更新される時間を稼ぐ。
      setTimeout(() => setPending(false), 400)
    }
  }

  const keys = inputMode === 'yn' ? ['Y', 'n'] : (options || [])
  if (keys.length === 0) return null

  return (
    <span className="prompt-reply-controls" data-testid="prompt-reply-controls">
      {keys.map(k => (
        <button
          key={k}
          type="button"
          className="prompt-reply-btn"
          disabled={pending}
          onClick={() => handleTap(k)}
          aria-label={`Send ${k}`}
          data-testid={`prompt-reply-btn-${k}`}
        >
          {k}
        </button>
      ))}
    </span>
  )
}
