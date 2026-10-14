// 声で聞いている印 (= 🔊 が ON のタブで人が打った文の頭に付ける `[voice]`)。
//
// エージェントには、 画面の 🔊 が ON かは見えない。 印が付いた文への返事は声で聞かれると分かれば、
// エージェントが声に向いた書き方 (= 短く・表や path を文に混ぜない) へ切り替えられる。 印はこの画面が
// 送る時に付け、 記録にもそのまま残る。 吹き出しの表示からは外す (= 言い方の印と同じ扱い)。
//
// claude の入力欄が頭の 1 文字で特別に扱う文 (= `/` の command、 `!` の shell、 `#` の memory) には
// 付けない (= 頭に印が入ると、 その意味が消えて普通の発話として送られる)。

export const VOICE_INPUT_MARK = '[voice]'

const SPECIAL_HEAD = /^[/!#]/
const MARKED = /^\[voice\][ \t]*/

// 送る文に印を付ける。 空の文と、 特別な頭の文はそのまま返す。
export function markVoiceInput(text) {
  if (typeof text !== 'string' || !text.trim() || SPECIAL_HEAD.test(text)) return text
  if (MARKED.test(text)) return text
  return `${VOICE_INPUT_MARK} ${text}`
}

// 表示する文から、 頭の印を外す (= 記録の文は変えない)。
export function hideVoiceInputMark(text) {
  if (typeof text !== 'string') return text
  return text.replace(MARKED, '')
}
