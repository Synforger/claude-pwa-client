// 声で聞いている印 (= そのタブの会話が開いている間に人が送った文の頭に付く `[voice]`)。
//
// エージェントには、 画面の 🔊 や 🎙 が入っているかは見えない。 印が付いた文への返事は声で聞かれると分かれば、
// エージェントが声に向いた書き方 (= 短く・表や path を文に混ぜない) へ切り替えられる。 印は backend が送信の口で
// 付け (= どれかの画面で会話が開いているか、 app の通話がつながっている間。 backend/core/speech.py の
// mark_voice_input)、 記録にもそのまま残る。 吹き出しの表示からは外す (= 言い方の印と同じ扱い)。

export const VOICE_INPUT_MARK = '[voice]'

const MARKED = /^\[voice\][ \t]*/

// 表示する文から、 頭の印を外す (= 記録の文は変えない)。
export function hideVoiceInputMark(text) {
  if (typeof text !== 'string') return text
  return text.replace(MARKED, '')
}
