// 声の配線: 届いた event → 声にする物を選ぶ (= listener.js) → 音にして鳴らす (= player.js)。
// 人の声は 🎙 → 録る (= recorder.js) → backend が聞き取った文 → そのタブへ送る。
// 通信は backend の声の口 (= docs/reference/voice.md)、 音は audio.js。

import { apiFetch } from '../../transport/http.ts'
import { translateHttpErrorDetail } from '../../utils/httpError.js'
import {
  getSnapshot, setVoiceAvailable, setVoiceMarks, setVoiceOn, setVoiceError, setVoiceListen, setVoiceListening,
} from '../../state/voice.js'
import { tRaw } from '../../i18n/t.js'
import { createListener } from './listener.js'
import { createPlayer } from './player.js'
import { unlockAudio, playSound } from './audio.js'
import { markVoiceInput } from './inputMark.js'
import { startRecording } from './recorder.js'

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

// そのタブへ送る文 (= 🔊 が ON の間は、 声で聞いている印を頭に付ける。 詳細 = inputMark.js)。
export function voiceInputText(sid, text) {
  return getSnapshot().on[sid] ? markVoiceInput(text) : text
}

// そのタブの agent が声を持つかと、 印の一覧を backend に訊いて、 store に写す。
export async function refreshVoiceAvailable(sid) {
  try {
    const r = await apiFetch(base(sid))
    const voice = r.ok ? await r.json() : null
    setVoiceAvailable(sid, voice?.enabled === true)
    setVoiceMarks(sid, voice?.enabled === true ? voice.marks : [])
    setVoiceListen(sid, voice?.enabled === true ? voice.listen?.max_seconds : null)
  } catch {
    setVoiceAvailable(sid, false)
    setVoiceMarks(sid, [])
    setVoiceListen(sid, null)
  }
}

// --- 🎙 (= 人の声) ---------------------------------------------------------------

// 録っている途中の物 (= タブの id ごと)。 recording.stop() で録った音、 timer は上限の長さで止める時計。
const recordings = new Map()

// 🎙 を押した時に呼ぶ (= 人が押した handler の中から)。 send(text) は、 聞き取った文をこのタブへ送る関数。
//   録っていない時: 話し始める。 返事を声で聞く状態にし (= 押した手の中で音を鳴らせるようにする)、 鳴っている
//                   返事はその場で止める (= 人が話し始めたら、 そちらが先)
//   録っている時:   録るのを止めて、 聞き取った文を送る
//   聞き取りを待っている時: 何もしない
export async function pressMic(sid, send, media) {
  const phase = getSnapshot().listening[sid]
  if (phase === 'hearing') return
  if (phase === 'recording') { await finishListening(sid, send); return }
  if (!getSnapshot().on[sid]) setVoice(sid, true)
  else player.stop(sid)
  setVoiceListening(sid, 'recording')
  let recording
  try {
    recording = await startRecording(media)
  } catch (error) {
    setVoiceListening(sid, null)
    setVoiceError(sid, tRaw('voice.mic_refused', { reason: error?.message || String(error) }))
    return
  }
  // 録り始めを待つ間に止められていれば (= タブを移った)、 マイクを閉じて終わる。
  if (getSnapshot().listening[sid] !== 'recording') { await recording.cancel(); return }
  const maxSeconds = getSnapshot().listen[sid]
  const timer = maxSeconds ? setTimeout(() => { finishListening(sid, send) }, maxSeconds * 1000) : null
  recordings.set(sid, { recording, timer })
}

async function finishListening(sid, send) {
  const held = recordings.get(sid)
  if (!held) return
  recordings.delete(sid)
  if (held.timer) clearTimeout(held.timer)
  setVoiceListening(sid, 'hearing')
  try {
    const sound = await held.recording.stop()
    // 待つ上限は置かない: 聞き取りは音の長さに比例して掛かり、 backend が engine を待つ上限で必ず返る。
    const r = await apiFetch(`${base(sid)}/transcription`, {
      method: 'POST', body: sound, headers: { 'Content-Type': sound.type || 'audio/webm' }, timeout: 0,
    })
    if (!r.ok) throw await refused(r)
    const text = ((await r.json()).text || '').trim()
    // 聞き取りを待つ間にタブを移っていれば送らない (= 送る関数は、 今見ているタブへ送る)。
    if (getSnapshot().listening[sid] !== 'hearing') return
    if (!text) { setVoiceError(sid, tRaw('voice.heard_nothing')); return }
    setVoiceError(sid, null)
    send(text)
  } catch (error) {
    console.warn('[voice] could not hear what was said:', error)
    setVoiceError(sid, error?.message || String(error))
  } finally {
    if (getSnapshot().listening[sid] === 'hearing') setVoiceListening(sid, null)
  }
}

// 🎙 を手放す (= タブを移った / 画面から消えた時)。 録っている音は捨て、 聞き取りを待っている文は送らない。
export async function cancelListening(sid) {
  const held = recordings.get(sid)
  recordings.delete(sid)
  if (held?.timer) clearTimeout(held.timer)
  setVoiceListening(sid, null)
  if (held) await held.recording.cancel()
}
