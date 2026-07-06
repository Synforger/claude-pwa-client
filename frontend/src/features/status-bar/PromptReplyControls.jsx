import { useState } from 'react'
import { useT } from '../../i18n/t.js'
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

// pane excerpt から自由記述 option (= "N. Type something") の数字を読む。 無ければ null。
// 位置 (= 最後の数字) では判定しない: claude の TUI は "Type something" の後に
// "Chat about this" 等の行を足すことがあり、 並び順は version で変わる。
export function freeTextDigit(entry) {
  const m = (entry?.excerpt || '').match(/(\d+)[.)]\s*Type something/i)
  return m ? m[1] : null
}

export async function sendRawKey(sid, key, enter) {
  try {
    await apiFetch(`/pty/${encodeURIComponent(sid)}/send-raw-key`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ key, enter: !!enter }),
    })
  } catch { /* 送信失敗はサイレント (= 通常 chip が消えないだけ、 再 tap で復帰) */ }
}

export function PromptReplyControls({ sid, entry, typing = false }) {
  const t = useT()
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

  // カーソル移動 (= ↑↓)。 Type something 選択中なら「カーソルが入力行から離れる」 ので
  // 回答入力中 flag も同時に下ろす (= 実機確認 2026-07-06: ↑↓ が text 入力からの正規の
  // 戻り道。 Esc は dialog ごとキャンセルなので使わない)。
  const handleArrow = (key) => {
    if (typing) setTypingAnswer(sid, false)
    handleTap(key, false)
  }

  // Type something 選択中 (= 回答入力中): 数字タップは文字化けするので数字を出さず、
  // ボタンと同格サイズの案内 + ↑↓ (= 選択肢への戻り道) だけを出す。
  if (typing && inputMode === 'numbers') {
    return (
      <span className="prompt-reply-controls" data-testid="prompt-reply-controls">
        <span className="prompt-typing-inline" data-testid="prompt-typing-inline">
          ✏️ {t('prompt.typing_answer_short')}
        </span>
        <button
          type="button"
          className="prompt-reply-btn"
          disabled={pending}
          onClick={() => handleArrow('Up')}
          aria-label="Back to options (move cursor up)"
          data-testid="prompt-reply-btn-up"
        >↑</button>
        <button
          type="button"
          className="prompt-reply-btn"
          disabled={pending}
          onClick={() => handleArrow('Down')}
          aria-label="Move cursor down"
          data-testid="prompt-reply-btn-down"
        >↓</button>
      </span>
    )
  }

  return (
    <span className="prompt-reply-controls" data-testid="prompt-reply-controls">
      {keys.map(k => (
        <button
          key={k}
          type="button"
          className="prompt-reply-btn"
          disabled={pending}
          onClick={() => {
            // "Type something" (= 自由記述の入口) の数字を選んだ瞬間に「回答入力中」
            // mode に切替える (= 以降の数字タップが text 入力に化ける事故を防ぐ)。
            // 数字は位置で仮定しない: claude は "Type something" の後に "Chat about
            // this" 等を足すことがある (= 2026-07-06 実測で 5 択化) ので、 pane の
            // excerpt から「N. Type something」 の N を直接読む。
            if (k === freeTextDigit(entry)) {
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
      {/* 数字モードの補助キー常設 (= 2026-07-06 実機 feedback で確定):
          ↑↓ = カーソル移動 (Type something からの復帰にも使う正規経路)、
          ␣ = multiSelect の toggle (単一選択では押す必要なし・無害)、
          ⏎ = multiSelect の確定 (multi では数字が toggle として働くため)。 */}
      {inputMode === 'numbers' && (
        <>
          <button
            type="button"
            className="prompt-reply-btn prompt-reply-btn-aux"
            disabled={pending}
            onClick={() => handleArrow('Up')}
            aria-label="Move cursor up"
            data-testid="prompt-reply-btn-up"
          >↑</button>
          <button
            type="button"
            className="prompt-reply-btn prompt-reply-btn-aux"
            disabled={pending}
            onClick={() => handleArrow('Down')}
            aria-label="Move cursor down"
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
            className="prompt-reply-btn prompt-reply-btn-aux"
            disabled={pending}
            onClick={() => handleTap('Enter', false)}
            aria-label="Confirm selection"
            data-testid="prompt-reply-btn-confirm"
          >⏎</button>
        </>
      )}
    </span>
  )
}
