// 声の大きさの倍率 (= その端末だけの値。 0 〜 2、 1 で engine の音のまま)。 🔊 の長押しのつまみが書き、 画面の
// 声と iPhone の app の通話の声の両方に掛かる。 localStorage に覚える (= Mac と iPhone で別の値)。 全端末に共通の
// 基準の大きさは agent の声の設定 (= backend の voice) が持ち、 これはその上に掛ける倍率。
import { createStore } from './_store.js'

const LS_KEY = 'cpc_v3_voice_volume'
// 前の鍵 (= iPhone の app の通話に backend の基準 `voice_call_gain_db` が掛かる前の値)。 ブラウザはそのまま引き継ぎ、
// app は 100% から始め直す (= 基準を下げたのに、 下げる前に絞ったつまみが残ると、 二重に小さくなる)
const LS_KEY_BEFORE_CALL_GAIN = 'cpc_v2_voice_volume'
export const VOLUME_MAX = 2

function stored(key) {
  const raw = localStorage.getItem(key)
  const value = Number(raw)
  return raw !== null && Number.isFinite(value) && value >= 0 && value <= VOLUME_MAX ? value : null
}

function initial() {
  try {
    const now = stored(LS_KEY)
    if (now !== null) return now
    const inApp = typeof window !== 'undefined' && window.Capacitor?.isNativePlatform?.()
    const before = inApp ? null : stored(LS_KEY_BEFORE_CALL_GAIN)
    if (before !== null) return before
  } catch { /* localStorage 不可 (= private mode 等) */ }
  return 1
}

const store = createStore({ volume: initial() }, { name: 'voiceVolume' })

export const getSnapshot = () => store.getSnapshot()
export const subscribe = (listener) => store.subscribe(listener)

export function setVoiceVolume(value) {
  const volume = Math.min(VOLUME_MAX, Math.max(0, Math.round(Number(value) * 100) / 100))
  if (!Number.isFinite(volume)) return
  store.setState(prev => (prev.volume === volume ? prev : { ...prev, volume }))
  try { localStorage.setItem(LS_KEY, String(volume)) } catch { /* ignore */ }
}
