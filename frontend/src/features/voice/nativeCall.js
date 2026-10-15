// iPhone の app (= repo の shell/) の中の会話: マイクと声を app が持ち、 backend の電話の口と WebRTC でつなぐ。
//
// 画面 (= WKWebView) は裏に回るとマイクも音も JavaScript も止まる。 app の native の部品 (= BackgroundVoice) は
// 裏でも動き続けるので、 会話をオンにしている間は、 声の区間・言い終えの判定・聞き取り・タブへの送信・返事の声を、
// 全部 backend の中の会話 (= backend/voice_call/) に任せる。 ブラウザで開いた画面には BackgroundVoice が無く、
// ここは使わない (= 画面の中で判定する会話のまま)。

import { API_BASE } from '../../constants.js'

// app の中なら BackgroundVoice の口、 ブラウザなら null。
export function nativeVoice() {
  const cap = typeof window !== 'undefined' ? window.Capacitor : null
  return cap?.isNativePlatform?.() ? cap.Plugins?.BackgroundVoice || null : null
}

// そのタブの電話の口の URL (= app の native の部品は、 画面の origin を知らないので絶対 URL で渡す)。 volume は
// その端末の声の大きさの倍率 (= backend の会話が声に掛ける)。 speech が false なら、 返事を声にしない会話で始める。
export function callUrl(sid, volume = 1, speech = true) {
  const url = new URL(`${API_BASE}/sessions/${encodeURIComponent(sid)}/voice/call`, window.location.href)
  url.searchParams.set('volume', String(volume))
  if (!speech) url.searchParams.set('speech', '0')
  return url.href
}

// app の会話を 1 本だけ持つ (= app の部品も backend の会話も、 1 本ずつ)。
//   onState(sid, state, message, { fatal })   connecting / connected / disconnected / error (= fatal: 通話が続けられ
//                                             ない error か。 app が言わなければ undefined)
//   onMic(sid, on)                            小窓 (= PiP) の再生 / 停止で、 app がマイクを入れた / 切った
export function createNativeCall({ plugin, onState, onMic = () => {} }) {
  let current = null
  let listening = false
  const listen = () => {
    if (listening) return
    listening = true
    plugin.addListener('state', ({ state, message, fatal } = {}) => {
      if (current) onState(current, state, message, { fatal })
    })
    plugin.addListener('mic', ({ on } = {}) => {
      if (current && typeof on === 'boolean') onMic(current, on)
    })
  }
  return {
    has: (sid) => current === sid,
    // 古い版の app は、 声の入 / 切と小窓で表示の口を持たない (= 呼ぶと「関数ではない」 で落ちる)
    get canSetSpeech() { return typeof plugin.setSpeech === 'function' },
    get canShowPicture() { return typeof plugin.showPicture === 'function' },
    async start(sid, { mic, volume = 1, speech = true }) {
      listen()
      current = sid
      await plugin.start({ url: callUrl(sid, volume, speech), mic })
    },
    async setSpeech(sid, on) {
      if (current === sid) await plugin.setSpeech({ on })
    },
    async showPicture(sid) {
      if (current === sid) await plugin.showPicture()
    },
    async setMic(sid, on) {
      if (current === sid) await plugin.setMic({ on })
    },
    async stop(sid) {
      if (current !== sid) return
      current = null
      await plugin.stop()
    },
  }
}
