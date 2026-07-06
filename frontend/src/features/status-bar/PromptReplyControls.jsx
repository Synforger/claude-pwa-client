import { useState } from 'react'
import { useT } from '../../i18n/t.js'
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

// カーソル (= ❯) が "Type something" 行に乗っているか (= 自由記述の入力中か) を pane の
// excerpt から直接読む。 ローカル flag で追わないのが要点: タップ / ↑↓ / 端末直叩きの
// どの経路でカーソルが動いても、 表示は常に pane の真値に追従する (= 2026-07-06 に
// ローカル flag 方式が 2 回実機で破綻した教訓)。
export function cursorOnTypeSomething(entry) {
  return /^\s*[❯▶➜→]\s*\d+[.)]\s*Type something/im.test(entry?.excerpt || '')
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

export function PromptReplyControls({ sid, entry }) {
  const t = useT()
  const [pending, setPending] = useState(false)
  if (!entry || !sid) return null
  // 表示状態は pane の現実 (= excerpt) だけから導出する
  const typing = cursorOnTypeSomething(entry)
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

  // カーソル移動 (= ↑↓)。 Type something からの正規の戻り道 (= 実機確認 2026-07-06、
  // Esc は dialog ごとキャンセルなので使わない)。 表示は次の excerpt 更新 (= send 後の
  // poke_now で ~100ms) が現実を映す。
  const handleArrow = (key) => {
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
          onClick={() => handleTap(k)}
          aria-label={`Send ${k}`}
          data-testid={`prompt-reply-btn-${k}`}
        >
          {k}
        </button>
      ))}
      {/* 数字モードの補助キー常設 (= 2026-07-06 実機 feedback で確定):
          ↑↓ = カーソル移動 (Type something からの復帰にも使う正規経路)、
          ⏎ = multiSelect の確定 (multi では数字自体が toggle として働くため)。
          ␣ は数字モードでは出さない (= 数字 toggle で足りる、 実機確認済み)。
          番号なし checkbox 型 picker 用の ␣ は arrows モード側に常設。 */}
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
            onClick={() => handleTap('Enter', false)}
            aria-label="Confirm selection"
            data-testid="prompt-reply-btn-confirm"
          >⏎</button>
        </>
      )}
    </span>
  )
}
