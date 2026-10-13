// 声の配線: 届いた event → 声にする物を選ぶ (= listener.js) → 音にして鳴らす (= player.js)。
// 通信は backend の声の口 (= docs/reference/voice.md)、 音は audio.js。

import { apiFetch } from '../../transport/http.ts'
import { translateHttpErrorDetail } from '../../utils/httpError.js'
import { getSnapshot, setVoiceAvailable, setVoiceMarks, setVoiceOn, setVoiceError } from '../../state/voice.js'
import { createListener } from './listener.js'
import { createPlayer } from './player.js'
import { unlockAudio, playSound } from './audio.js'

const base = (sid) => `/sessions/${encodeURIComponent(sid)}/voice`

async function refused(response) {
  const detail = (await response.json().catch(() => null))?.detail
  return new Error(translateHttpErrorDetail(detail, `HTTP ${response.status}`))
}

const player = createPlayer({
  utterances: async (sid, text, signal) => {
    const r = await apiFetch(`${base(sid)}/utterances`, { method: 'POST', jsonBody: { text }, signal })
    if (!r.ok) throw await refused(r)
    return (await r.json()).utterances || []
  },
  sound: async (sid, utterance, signal) => {
    // 待つ上限は置かない: 1 文の合成は文の長さに比例して掛かり、 backend が engine を待つ上限で必ず返る。
    const r = await apiFetch(`${base(sid)}/synthesis`, { method: 'POST', jsonBody: utterance, signal, timeout: 0 })
    if (!r.ok) throw await refused(r)
    return r.arrayBuffer()
  },
  play: (_sid, data) => playSound(data),
  onError: (sid, error) => {
    console.warn('[voice] could not say a reply:', error)
    setVoiceError(sid, error?.message || String(error))
  },
  onPlayed: (sid) => setVoiceError(sid, null),
})

const listener = createListener({
  isOn: (sid) => !!getSnapshot().on[sid],
  say: (sid, text) => player.say(sid, text),
})

// 届いた event を 1 つ渡す (= チャットの event の受け口から呼ぶ)。 history = 履歴の読み込みで届いた物か。
export function observeVoiceEvent(sid, event, { history = false } = {}) {
  listener.observe(sid, event, { history })
}

// 🔊 を押した時に呼ぶ (= 人が押した handler の中から。 音を鳴らせるようにするのがここ)。
export function setVoice(sid, on) {
  if (on) {
    try {
      unlockAudio()
    } catch (error) {
      setVoiceError(sid, error?.message || String(error))
      return
    }
    setVoiceError(sid, null)
    listener.start(sid)
    setVoiceOn(sid, true)
  } else {
    listener.stop(sid)
    player.stop(sid)
    setVoiceOn(sid, false)
    setVoiceError(sid, null)
  }
}

// そのタブの agent が声を持つかと、 印の一覧を backend に訊いて、 store に写す。
export async function refreshVoiceAvailable(sid) {
  try {
    const r = await apiFetch(base(sid))
    const voice = r.ok ? await r.json() : null
    setVoiceAvailable(sid, voice?.enabled === true)
    setVoiceMarks(sid, voice?.enabled === true ? voice.marks : [])
  } catch {
    setVoiceAvailable(sid, false)
    setVoiceMarks(sid, [])
  }
}
