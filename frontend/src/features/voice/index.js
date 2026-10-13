// features/voice 配線 entry。
//
// 声 (= agent の返事を音で聞く)。 上部の 🔊 (= VoiceToggle) は Topbar が置き、 届いた event は
// チャットの受け口が observeVoiceEvent へ渡す。 overlay も registry への登録も持たない。

export { observeVoiceEvent } from './voice.js'
