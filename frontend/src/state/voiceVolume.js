// 声の大きさの倍率 (= その端末だけの値。 0 〜 2、 1 で engine の音のまま)。 🔊 の長押しのつまみが書き、 画面の
// 声と iPhone の app の通話の声の両方に掛かる。 localStorage に覚える (= Mac と iPhone で別の値)。 全端末に共通の
// 基準の大きさは agent の声の設定 (= backend の voice) が持ち、 これはその上に掛ける倍率。
import { createStore } from './_store.js'

const LS_KEY = 'cpc_v2_voice_volume'
export const VOLUME_MAX = 2

function initial() {
  try {
    const stored = localStorage.getItem(LS_KEY)
    const value = Number(stored)
    if (stored !== null && Number.isFinite(value) && value >= 0 && value <= VOLUME_MAX) return value
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
