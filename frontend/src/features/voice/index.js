// features/voice 配線 entry。
//
// 声 (= agent の返事を音で聞く)。 上部の 🔊 (= VoiceToggle) は Topbar が置き、 届いた event は
// チャットの受け口が observeVoiceEvent へ渡す。 吹き出しは、 言い方の印を hideMarks で表示から外す。
// overlay も registry への登録も持たない。

export { observeVoiceEvent } from './voice.js'
export { hideMarks } from './marks.js'
export { useVoiceMarks } from './useVoiceMarks.js'
