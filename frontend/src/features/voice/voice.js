// 声の配線: 届いた event → 声にする物を選ぶ (= listener.js) → 音にして鳴らす (= player.js)。
// 人の声は、 会話を開いている間 (= conversation.js) 、 言い終えるたびに backend が文字にして、 そのタブへ送る。
// 🔊 にできるのは同時に 1 つのタブだけで、 別のタブを見ている間も、 会話はそのタブで続く。
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
import { nativeVoice, createNativeCall } from './nativeCall.js'
import { getSnapshot as volumeOf, setVoiceVolume } from '../../state/voiceVolume.js'

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

// iPhone の app の中の会話 (= マイクと声を app が持つ。 ブラウザでは null)。 最初に使う時に作る。
let nativeCall
function call() {
  if (nativeCall === undefined) {
    const plugin = nativeVoice()
    nativeCall = plugin ? createNativeCall({ plugin, onState: onNativeState }) : null
  }
  return nativeCall
}

const listener = createListener({
  // app の会話の間は、 返事の声も backend の中の会話が鳴らす (= 画面では鳴らさない)
  isOn: (sid) => !!getSnapshot().on[sid] && !call()?.has(sid),
  say: (sid, text) => player.say(sid, text),
})

// 🔊 がオンのタブ (= 空白で区切った文字列。 中身が同じなら同じ値なので、 そのまま store の写しに使える)。
export const voiceOnSids = () => Object.keys(getSnapshot().on).sort().join(' ')
export { subscribe as subscribeVoice }

// 聞き取った文をタブへ送る関数 (= send(sid, text)。 チャットの画面が登録する)。 会話は開いた時の送信関数を
// 掴まず、 送る時にここを通す (= 見ているタブが変わっても、 🔊 のタブへ送る)。
let sender = null
export function setVoiceSender(send) {
  sender = send
}

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

// 🎙 でマイクを開いたタブ (= この画面の中だけ覚える。 開いたままにしたタブは、 次に声をオンにした時もマイクを開く。
// 選んでいなければ、 声だけを鳴らしてマイクは取らない)
const micWanted = new Set()

// 入力欄の 🔊 を押した時に呼ぶ (= 人が押した handler の中から。 音とマイクを扱えるようにするのがここ)。
//   オフの時: 返事を声で鳴らし始める。 その agent が声を聞き取り、 このタブで 🎙 を開いたままにしていれば、 マイクも開く。
//            別のタブの声は閉じる (= 🔊 は 1 つのタブだけ)
//   オンの時: 全部閉じる。 マイクを閉じ、 返事も鳴らさない
export function toggleVoice(sid) {
  if (getSnapshot().on[sid]) { closeConversation(sid); return }
  for (const other of Object.keys(getSnapshot().on)) closeConversation(other)
  if (call() && getSnapshot().listen[sid]) { openCall(sid); return }
  setVoice(sid, true)
  if (getSnapshot().on[sid] && getSnapshot().listen[sid] && micWanted.has(sid)) openMic(sid)
}

// 入力欄の 🎙 を押した時に呼ぶ (= 声がオンの間だけ出る)。 マイクを開くと閉じるを入れ替える。 声はそのまま鳴る
// (= マイクを閉じている間も、 打って送った文には声で聞いている印が付く)。
export function toggleMic(sid) {
  if (!getSnapshot().on[sid] || !getSnapshot().listen[sid]) return
  if (call()?.has(sid)) {
    if (micWanted.has(sid)) micWanted.delete(sid)
    else micWanted.add(sid)
    setVoicePhase(sid, micWanted.has(sid) ? 'listening' : null)
    call().setMic(sid, micWanted.has(sid)).catch((error) => setVoiceError(sid, error?.message || String(error)))
    return
  }
  if (conversations.has(sid)) {
    micWanted.delete(sid)
    closeMic(sid)
  } else {
    micWanted.add(sid)
    openMic(sid)
  }
}

function openMic(sid) {
  const entry = { closed: false, handle: null, stream: null, audioContext: null }
  conversations.set(sid, entry)
  setVoiceError(sid, null)
  setVoicePhase(sid, 'starting')
  try {
    entry.audioContext = new AudioContext()
    entry.stream = navigator.mediaDevices.getUserMedia(MIC)
    entry.stream.catch(() => {})
  } catch (error) {
    refuseMic(sid, error)
    return
  }
  open(sid, entry).catch((error) => {
    if (entry.closed) return
    console.warn('[voice] could not open the microphone:', error)
    const micRefused = error?.name === 'NotAllowedError' || error?.name === 'NotFoundError'
    closeMic(sid)
    if (micRefused) refuseMic(sid, error)
    else setVoiceError(sid, error?.message || String(error))
  })
}

function refuseMic(sid, error) {
  closeMic(sid)
  setVoiceError(sid, tRaw('voice.mic_refused', { reason: error?.message || String(error) }))
}

async function open(sid, entry) {
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
    // 声でない音 (= 物音) は、 文字にすると空になり、 ここへは来ない。 送る時に前の turn の声は全部止め、
    // 新しい turn が始まるまで返事を鳴らさない (= listener.js)
    send: (text) => {
      if (entry.closed) return
      player.stop(sid)
      listener.holdUntilNextTurn(sid)
      sender?.(sid, text)
    },
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

// 会話を閉じる (= 🔊 を押し直した / 別のタブで 🔊 にした / 別の画面が会話を開いた時)。 マイクを閉じ、
// 返事も鳴らさない。
export function closeConversation(sid) {
  if (call()?.has(sid)) {
    call().stop(sid).catch(() => {})
    setVoicePhase(sid, null)
    setVoiceOn(sid, false)
    setVoiceError(sid, null)
    return
  }
  closeMic(sid)
  setVoice(sid, false)
}

// app の会話を開く (= 声もマイクも app が持ち、 判定から先は backend の中で回る)。
function openCall(sid) {
  setVoiceError(sid, null)
  setVoiceOn(sid, true)
  setVoicePhase(sid, micWanted.has(sid) ? 'starting' : null)
  call().start(sid, { mic: micWanted.has(sid), volume: volumeOf().volume }).catch((error) => {
    closeConversation(sid)
    setVoiceError(sid, error?.message || String(error))
  })
}

// app の会話の知らせ (= つながった / 切れた / 失敗した)。
function onNativeState(sid, state, message) {
  if (state === 'connected') {
    setVoicePhase(sid, micWanted.has(sid) ? 'listening' : null)
  } else if (state === 'error') {
    closeConversation(sid)
    setVoiceError(sid, message || state)
  } else if (state === 'disconnected' && getSnapshot().on[sid]) {
    // backend が会話を終えた (= 別の画面が会話を開いた / backend が止まった)
    closeConversation(sid)
  }
}

// テストの間で、 🎙 を開いたタブと開いている会話を忘れる
export function _resetForTest() {
  micWanted.clear()
  conversations.clear()
  nativeCall = undefined
}

// マイクだけを閉じる (= 声はそのまま鳴る)。
function closeMic(sid) {
  const entry = conversations.get(sid)
  conversations.delete(sid)
  setVoicePhase(sid, null)
  if (!entry) return
  entry.closed = true
  entry.handle?.close()
  entry.stream?.then((stream) => { for (const track of stream.getTracks()) track.stop() }).catch(() => {})
  entry.audioContext?.close().catch(() => {})
  apiFetch(`${base(sid)}/conversation`, { method: 'DELETE', jsonBody: { client: CLIENT } }).catch(() => {})
}

// 🔊 の長押しのつまみを動かした時に呼ぶ。 その端末の声の大きさを覚え、 画面の声にはその場で、 app の通話の声には
// 次の文から効かせる (= 通話の声は backend の中で作るので、 backend へ伝える)。
export function changeVolume(sid, volume) {
  setVoiceVolume(volume)
  if (!call()?.has(sid)) return
  apiFetch(`${base(sid)}/call/volume`, { method: 'POST', jsonBody: { volume: volumeOf().volume } })
    .catch((error) => setVoiceError(sid, error?.message || String(error)))
}
