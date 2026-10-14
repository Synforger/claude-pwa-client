// features/voice 配線 entry。
//
// 声 (= agent と声で話す)。 入力欄の声のボタン (= VoiceButtons) は ChatInput が置き、 届いた event は
// チャットの受け口が observeVoiceEvent へ渡す。 吹き出しは、 言い方の印を hideMarks で表示から外す。
// 会話を開いている間に送る文は voiceInputText が印を付け、 吹き出しは hideVoiceInputMark で表示から外す。
// overlay も registry への登録も持たない。

export { observeVoiceEvent, voiceInputText } from './voice.js'
export { hideMarks } from './marks.js'
export { hideVoiceInputMark } from './inputMark.js'
export { useVoiceMarks } from './useVoiceMarks.js'
