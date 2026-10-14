// 声の配線: 届いた event → 声にする物を選ぶ (= listener.js) → 音にして鳴らす (= player.js)。
// 人の声は、 会話を開いている間 (= conversation.js) 、 言い終えるたびに backend が文字にして、 そのタブへ送る。
// 通信は backend の声の口 (= docs/reference/voice.md)、 音は audio.js。

import { apiFetch } from '../../transport/http.ts'
import { translateHttpErrorDetail } from '../../utils/httpError.js'
import {
  getSnapshot, subscribe, setVoiceAvailable, setVoiceMarks, setVoiceOn, setVoiceError, setVoiceListen, setVoiceTurn,
  setVoicePhase, setVoiceSpeaking, setVoiceConversation,
} from '../../state/voice.js'
import { tRaw } from '../../i18n/t.js'
import { createListener } from './listener.js'
import { createPlayer } from './player.js'
import { unlockAudio, playSound } from './audio.js'
import { markVoiceInput } from './inputMark.js'

const base = (sid) => `/sessions/${encodeURIComponent(sid)}/voice`

async function refused(response) {
  const detail = (await response.json().catch(() => null))?.detail
  return Object.assign(new Error(translateHttpErrorDetail(detail, `HTTP ${response.status}`)), { code: detail?.code })
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
  onBusy: (sid, busy) => setVoiceSpeaking(sid, busy),
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
    setVoiceTurn(sid, voice?.enabled === true && voice.turn === true)
    setVoiceConversation(sid, voice?.enabled === true ? voice.conversation : null)
  } catch {
    setVoiceAvailable(sid, false)
    setVoiceMarks(sid, [])
    setVoiceListen(sid, false)
    setVoiceTurn(sid, false)
    setVoiceConversation(sid, null)
  }
}

// --- 会話 (= 人の声) ---------------------------------------------------------------

// この画面の名前 (= 会話を開いていられるのは 1 つのタブに 1 つの画面。 backend はこの名前で持ち主を見分ける)。
const CLIENT = `screen-${Math.random().toString(36).slice(2, 12)}`
const conversations = new Map()   // sid -> { closed, handle, stream, audioContext }

const MIC = { audio: { channelCount: 1, echoCancellation: true, autoGainControl: true, noiseSuppression: true } }

// 言い終えた声 (= WAV の Blob) を backend に文字にしてもらう (= 声が聞き取れなければ空の文)。
export async function transcribe(sid, sound) {
  // 待つ上限は置かない: 聞き取りは音の長さに比例して掛かり、 backend が engine を待つ上限で必ず返る。
  const r = await apiFetch(`${base(sid)}/transcription`, {
    method: 'POST', body: sound, timeout: 0,
    headers: { 'Content-Type': sound.type || 'audio/wav', 'X-Voice-Conversation': CLIENT },
  })
  if (!r.ok) throw await refused(r)
  return ((await r.json()).text || '').trim()
}

function speakingOf(sid) {
  return {
    isSpeaking: () => !!getSnapshot().speaking[sid],
    subscribeSpeaking: (onChange) => {
      let was = !!getSnapshot().speaking[sid]
      return subscribe(() => {
        const now = !!getSnapshot().speaking[sid]
        if (now !== was) { was = now; onChange(now) }
      })
    },
  }
}

// 入力欄の会話のボタンを押した時に呼ぶ (= 人が押した handler の中から。 音とマイクを扱えるようにするのがここ)。
// send(text) は、 聞き取った文をこのタブへ送る関数。
//   開いていない時: 開く。 返事を声で鳴らし始め、 その agent が声を聞き取るなら、 マイクを開いて聞き始める
//   開いている時:   閉じる。 マイクを閉じ、 返事も鳴らさない
export function toggleConversation(sid, send) {
  if (getSnapshot().on[sid]) { closeConversation(sid); return }
  setVoice(sid, true)
  if (!getSnapshot().on[sid] || !getSnapshot().listen[sid]) return
  const entry = { closed: false, handle: null, stream: null, audioContext: null }
  conversations.set(sid, entry)
  setVoicePhase(sid, 'starting')
  try {
    entry.audioContext = new AudioContext()
    entry.stream = navigator.mediaDevices.getUserMedia(MIC)
    entry.stream.catch(() => {})
  } catch (error) {
    refuseMic(sid, error)
    return
  }
  open(sid, entry, send).catch((error) => {
    if (entry.closed) return
    console.warn('[voice] could not open the conversation:', error)
    const micRefused = error?.name === 'NotAllowedError' || error?.name === 'NotFoundError'
    closeConversation(sid)
    if (micRefused) refuseMic(sid, error)
    else setVoiceError(sid, error?.message || String(error))
  })
}

function refuseMic(sid, error) {
  closeConversation(sid)
  setVoiceError(sid, tRaw('voice.mic_refused', { reason: error?.message || String(error) }))
}

async function open(sid, entry, send) {
  const claimed = await apiFetch(`${base(sid)}/conversation`, { method: 'POST', jsonBody: { client: CLIENT } })
  if (!claimed.ok) throw await refused(claimed)
  // 間の取り方は、 開くたびに取り直す (= agent が調整の file を書き換えた分を、 次に開いた時から使う)
  await refreshVoiceAvailable(sid)
  await entry.stream
  const { openConversation } = await import('./conversation.js')
  if (entry.closed) return
  const settings = getSnapshot().conversation[sid]
  if (!settings) throw new Error(tRaw('voice.conversation_unavailable'))
  const handle = await openConversation({
    audioContext: entry.audioContext,
    stream: entry.stream,
    turnModelUrl: getSnapshot().turn[sid] ? `${base(sid)}/turn-model` : null,
    settings,
    fetchModel: async (url) => {
      const r = await apiFetch(url, { timeout: 0 })
      if (!r.ok) throw await refused(r)
      return r.arrayBuffer()
    },
    transcribe: async (wav) => {
      try {
        return await transcribe(sid, wav)
      } catch (error) {
        if (error?.code === 'voice_conversation_elsewhere') {
          closeConversation(sid)
          setVoiceError(sid, tRaw('voice.conversation_elsewhere'))
          return ''
        }
        throw error
      }
    },
    // 声でない音 (= 物音) は、 文字にすると空になり、 ここへは来ない
    send: (text) => { if (!entry.closed) send(text) },
    // 返事の途中で人が話し始めた: 鳴っている音と、 まだ鳴らしていない文を捨てる (= 次の返事はまた鳴らす)
    interrupt: () => player.stop(sid),
    ...speakingOf(sid),
    onPhase: (phase) => { if (!entry.closed) setVoicePhase(sid, phase) },
    onError: (error) => {
      if (entry.closed) return
      console.warn('[voice] a turn could not be sent:', error)
      setVoiceError(sid, error?.message || String(error))
    },
  })
  if (entry.closed) { await handle.close(); return }
  entry.handle = handle
}

// 会話を閉じる (= ボタンを押し直した / タブを移った / 画面から消えた時)。 マイクを閉じ、 返事も鳴らさない。
export function closeConversation(sid) {
  const entry = conversations.get(sid)
  conversations.delete(sid)
  setVoice(sid, false)
  setVoicePhase(sid, null)
  if (!entry) return
  entry.closed = true
  entry.handle?.close()
  entry.stream?.then((stream) => { for (const track of stream.getTracks()) track.stop() }).catch(() => {})
  entry.audioContext?.close().catch(() => {})
  apiFetch(`${base(sid)}/conversation`, { method: 'DELETE', jsonBody: { client: CLIENT } }).catch(() => {})
}
