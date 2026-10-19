// 声の配線: 届いた event → 声にする物を選ぶ (= listener.js) → 音にして鳴らす (= player.js)。
// 人の声は、 会話を開いている間 (= conversation.js) 、 言い終えるたびに backend が文字にして、 そのタブへ送る。
// 🔊 にできるのは同時に 1 つのタブだけで、 別のタブを見ている間も、 会話はそのタブで続く。
// 通信は backend の声の口 (= docs/reference/voice.md)、 音は audio.js。

import { apiFetch } from '../../transport/http.ts'
import { translateHttpErrorDetail } from '../../utils/httpError.js'
import {
  getSnapshot, subscribe, setVoiceAvailable, setVoiceMarks, setVoiceOn, setVoiceError, setVoiceListen, setVoiceTurn,
  setVoicePhase, setVoiceSpeaking, setVoiceConversation, setVoiceQuiet,
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
    nativeCall = plugin ? createNativeCall({ plugin, onState: onNativeState, onMic: onNativeMic }) : null
  }
  return nativeCall
}

const listener = createListener({
  // app の会話の間は、 返事の声も backend の中の会話が鳴らす (= 画面では鳴らさない)
  isOn: (sid) => !!getSnapshot().on[sid] && !call()?.has(sid) && !getSnapshot().quiet[sid],
  say: (sid, text) => player.say(sid, text),
  cut: (sid) => player.stop(sid),
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

// 話している途中の言葉が取れた: タブの turn の実行中なら止める (= 止めたか)。
export async function interruptTurn(sid) {
  const r = await apiFetch(`${base(sid)}/interruption`, {
    method: 'POST', headers: { 'X-Voice-Conversation': CLIENT },
  })
  if (!r.ok) throw await refused(r)
  return !!(await r.json()).stopped
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

// 🎙 でマイクを開いているタブ (= この画面の中だけ覚える)
const micWanted = new Set()

// 入力欄の声のボタンは 2 つで、 それぞれ別に入 / 切できる: 🔊 = agent の返事の声、 🎙 = 人のマイク。 どちらかが入って
// いる間は会話がつながり (= 🔊 は 1 つのタブだけ。 別のタブで始めると、 前のタブの会話は閉じる)、 両方切ると会話を
// 終える。 🎙 だけで始めると、 声の入力だけで返事は声にしない会話になる (= 返事は文字と、 app の小窓で読む)。
// どちらも人が押した handler の中から呼ぶ (= 音とマイクを扱えるようにするのがここ)。

// 会話を始める (= 声を鳴らすかは quiet、 マイクを開くかは micWanted で決めてから呼ぶ)。
function startConversation(sid) {
  for (const other of Object.keys(getSnapshot().on)) closeConversation(other, 'another tab started a conversation')
  if (call() && getSnapshot().listen[sid]) { openCall(sid); return }
  setVoice(sid, true)
  if (getSnapshot().on[sid] && getSnapshot().listen[sid] && micWanted.has(sid)) openMic(sid)
}

// マイクが開いているか (= app の会話では app に頼んだ状態、 画面の会話では開いている会話が在るか)。
function micOpen(sid) {
  return call()?.has(sid) ? micWanted.has(sid) : conversations.has(sid)
}

// 返事を声にするか (= 会話の間。 切にすると鳴っている声も止める。 マイクと、 app の小窓の文字はそのまま)。
function setSpeech(sid, on) {
  setVoiceQuiet(sid, !on)
  if (call()?.has(sid)) {
    logCall(sid, 'speech', { on })
    call().setSpeech(sid, on).catch((error) => setVoiceError(sid, error?.message || String(error)))
  } else if (!on) {
    player.stop(sid)
  }
}

// 入力欄の 🔊 を押した時に呼ぶ。
//   会話していない時: 返事を声で鳴らす会話を始める (= マイクは取らない)
//   声を鳴らしている時: 声を止める。 マイクも閉じていれば会話を終える
//   声を止めている時: 声を鳴らす
// 声の入 / 切を受け付けない古い iPhone の app の会話では、 押すと会話を終える (= 前の 🔊 と同じ)。
export function toggleVoice(sid) {
  const snap = getSnapshot()
  if (!snap.on[sid]) {
    micWanted.delete(sid)
    setVoiceQuiet(sid, false)
    startConversation(sid)
    return
  }
  if (call()?.has(sid) && !call().canSetSpeech) { closeConversation(sid, 'the voice button (an app without the voice switch)'); return }
  if (snap.quiet[sid]) { setSpeech(sid, true); return }
  if (micOpen(sid)) { setSpeech(sid, false); return }
  closeConversation(sid, 'the voice button with the microphone closed')
}

// Siri の「通話」 (= app を開いた URL の call) で呼ぶ: 返事を声にして、 マイクも開いた会話にする。 会話して
// いれば、 足りない方 (= 声 / マイク) だけを入れる。 開いたばかりのタブは声を持つかがまだ分からないので、 先に訊く。
export async function startCall(sid) {
  if (!sid) return
  await refreshVoiceAvailable(sid)
  const snap = getSnapshot()
  if (!snap.available[sid]) return
  if (!snap.on[sid]) {
    if (snap.listen[sid]) micWanted.add(sid)
    else micWanted.delete(sid)
    setVoiceQuiet(sid, false)
    startConversation(sid)
    return
  }
  if (snap.quiet[sid]) setSpeech(sid, true)
  if (snap.listen[sid] && !micOpen(sid)) toggleMic(sid)
}

// iPhone の app の中で、 そのタブの通話がつながっていて、 app が小窓を出せる版か (= ⋯ メニューの「小窓で表示」)。
export function hasAppCall(sid) {
  return !!sid && !!call()?.has(sid) && !!getSnapshot().on[sid] && call().canShowPicture
}

// 通話の小窓 (= PiP) を今出す (= 自動で出なかった時。 出せなければ理由を声のボタンの上に出す)。
export function showCallPicture(sid) {
  if (!hasAppCall(sid)) return
  call().showPicture(sid).catch((error) => setVoiceError(sid, error?.message || String(error)))
}


// 入力欄の 🎙 を押した時に呼ぶ (= その agent が声を聞き取る時だけ出る)。
//   会話していない時: 声の入力だけの会話を始める (= 返事は声にしない)
//   会話している時: マイクを開く / 閉じる。 閉じた時に声も止めていれば、 会話を終える
export function toggleMic(sid) {
  const snap = getSnapshot()
  if (!snap.listen[sid]) return
  if (!snap.on[sid]) {
    micWanted.add(sid)
    setVoiceQuiet(sid, true)
    startConversation(sid)
    return
  }
  const closing = micOpen(sid)
  if (closing && snap.quiet[sid]) { micWanted.delete(sid); closeConversation(sid, 'the microphone button with the voice off'); return }
  if (call()?.has(sid)) {
    if (closing) micWanted.delete(sid)
    else micWanted.add(sid)
    setVoicePhase(sid, micWanted.has(sid) ? 'listening' : null)
    logCall(sid, 'mic', { on: micWanted.has(sid), from: 'screen' })
    call().setMic(sid, micWanted.has(sid)).catch((error) => setVoiceError(sid, error?.message || String(error)))
    return
  }
  if (closing) {
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
          closeConversation(sid, 'another screen opened the conversation')
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
    // 話している途中に言葉が取れた: 話し終えるのを待たずに、 タブの turn を止める
    stopTurn: () => interruptTurn(sid),
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
// 返事も鳴らさない。 reason = なぜ閉じるか (= app の通話では backend の log に残す)。
export function closeConversation(sid, reason = 'closed') {
  if (call()?.has(sid)) {
    logCall(sid, 'close', { reason })
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
  const speech = !getSnapshot().quiet[sid]
  logCall(sid, 'open', { mic: micWanted.has(sid), speech })
  call().start(sid, { mic: micWanted.has(sid), volume: volumeOf().volume, speech }).catch((error) => {
    closeConversation(sid, 'the app could not start the call')
    setVoiceError(sid, error?.message || String(error))
  })
}

// 画面が立ち上がった時に呼ぶ: app が通話を持ったままなら (= 通話の途中で画面が読み込み直された)、 その通話を
// 今の会話として引き取り、 🔊 と 🎙 の表示を app の状態に合わせる (= 画面ではマイクが切れて見えるのに、 app では
// 聞き取りが続く形を残さない)。
export async function adoptAppCall() {
  if (!call()) return
  const found = await call().adopt().catch(() => null)
  if (!found || getSnapshot().on[found.sid]) return
  if (found.mic) micWanted.add(found.sid)
  else micWanted.delete(found.sid)
  setVoiceQuiet(found.sid, !found.speech)
  setVoiceOn(found.sid, true)
  setVoicePhase(found.sid, found.mic ? 'listening' : null)
  logCall(found.sid, 'adopt', { mic: found.mic, speech: found.speech })
}

// 小窓 (= PiP) の再生 / 停止で app がマイクを切り替えた: 🎙 の表示を合わせる (= 入力欄の 🎙 と同じ状態)。
function onNativeMic(sid, on) {
  logCall(sid, 'mic', { on, from: 'picture' })
  if (on) micWanted.add(sid)
  else micWanted.delete(sid)
  setVoicePhase(sid, on ? 'listening' : null)
}

// app の会話の知らせ (= つながった / 切れた / 失敗した)。
function onNativeState(sid, state, message, { fatal } = {}) {
  logCall(sid, 'state', { state, ...(message ? { message: String(message).slice(0, 300) } : {}) })
  if (state === 'connected') {
    setVoicePhase(sid, micWanted.has(sid) ? 'listening' : null)
  } else if (state === 'error' && !isFatal(fatal, message)) {
    // 1 文を言えなかった等、 通話は続けられる error: 理由だけ出し、 通話は閉じない
    setVoiceError(sid, errorText(message) || state)
  } else if (state === 'error') {
    closeConversation(sid, 'the app reported an error the call cannot go on with')
    setVoiceError(sid, message || state)
  } else if (state === 'disconnected' && getSnapshot().on[sid]) {
    // backend が会話を終えた (= 別の画面が会話を開いた / backend が止まった)
    closeConversation(sid, 'the app reported the call disconnected')
  }
}

// app の通話の開け閉めとマイクの入 / 切を backend の log へ (= logs/backend.log の `sw-log` の行。 通話が途中で
// 切れた時に、 画面が閉じたのか app が切れたと言ったのか、 どのボタンだったのかを後から見分ける)。
function logCall(sid, stage, detail = {}) {
  apiFetch('/log/sw', { method: 'POST', jsonBody: { stage: `voice:${stage}`, sid, ...detail } }).catch(() => {})
}

// 通話を続けられない error か。 app 1.9.0 は fatal を項目で渡さず、 Pipecat の error の中身 (= `"fatal":false` を
// 含む JSON) を Swift の文字列のまま渡す (= `RTVIMessageInbound(... data: Optional("{\"fatal\":false, ...}"))`)。
// 次の版の app は fatal を項目で渡す。 どちらも無ければ、 続けられない error として扱う
function isFatal(fatal, message) {
  if (typeof fatal === 'boolean') return fatal
  return !/\\?"fatal\\?"\s*:\s*false/.test(String(message || ''))
}

// error の文 (= Pipecat の error の中身の `error` を取り出す。 取り出せなければ渡された文のまま)
function errorText(message) {
  const found = /\\?"error\\?"\s*:\s*\\?"((?:[^"\\]|\\[^"])*)\\?"/.exec(String(message || ''))
  return found ? found[1] : message
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

// 🔊 の長押しのつまみを動かした時に呼ぶ。 その端末の声の大きさを覚え、 画面の声にも app の通話の声にもその場で効かせる
// (= 通話の声は backend の中で送るので、 backend へ伝える)。
export function changeVolume(sid, volume) {
  setVoiceVolume(volume)
  if (!call()?.has(sid)) return
  // app にも覚えさせる (= 端末の操作のために通話を外した後、 同じ大きさで掛け直す)
  call().setVolume(sid, volumeOf().volume).catch(() => {})
  apiFetch(`${base(sid)}/call/volume`, { method: 'POST', jsonBody: { volume: volumeOf().volume } })
    .catch((error) => setVoiceError(sid, error?.message || String(error)))
}
