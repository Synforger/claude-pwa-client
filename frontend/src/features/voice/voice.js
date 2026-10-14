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
    setVoiceListen(sid, voice?.enabled === true && voice.listen === true)
  } catch {
    setVoiceAvailable(sid, false)
    setVoiceMarks(sid, [])
    setVoiceListen(sid, false)
  }
}

// --- 🎙 (= 人の声) ---------------------------------------------------------------

// 録っている途中の物 (= タブの id ごと。 stop() で録った音、 cancel() で捨てる)。
const recordings = new Map()

// 録った音を backend に聞き取らせて、 その文を返す (= 声が聞き取れなければ空の文)。
export async function transcribe(sid, sound) {
  // 待つ上限は置かない: 聞き取りは音の長さに比例して掛かり、 backend が engine を待つ上限で必ず返る。
  const r = await apiFetch(`${base(sid)}/transcription`, {
    method: 'POST', body: sound, headers: { 'Content-Type': sound.type || 'audio/webm' }, timeout: 0,
  })
  if (!r.ok) throw await refused(r)
  return ((await r.json()).text || '').trim()
}

// 🎙 を押し始めた時に呼ぶ (= 人が押した handler の中から)。 返事を声で聞く状態にし (= 押した手の中で音を鳴らせる
// ようにする)、 鳴っている返事はその場で止める (= 人が話し始めたら、 そちらが先)。 押している間、 録る。
export async function startListening(sid, media) {
  if (getSnapshot().listening[sid]) return
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
  // マイクが開く前に離された / タブを移った: マイクを閉じて終わる。
  if (getSnapshot().listening[sid] !== 'recording') { await recording.cancel(); return }
  recordings.set(sid, recording)
}

// 🎙 を離した時に呼ぶ。 録った音を聞き取らせて、 その文を send(text) でこのタブへ送る。
// マイクがまだ開いていなければ (= 許可を訊かれている間など)、 録り始めを取りやめる。
export async function finishListening(sid, send) {
  const recording = recordings.get(sid)
  if (!recording) {
    if (getSnapshot().listening[sid] === 'recording') setVoiceListening(sid, null)
    return
  }
  recordings.delete(sid)
  setVoiceListening(sid, 'hearing')
  try {
    const text = await transcribe(sid, await recording.stop())
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
  const recording = recordings.get(sid)
  recordings.delete(sid)
  setVoiceListening(sid, null)
  if (recording) await recording.cancel()
}
