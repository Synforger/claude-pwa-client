// 会話の配線: マイク → 声の区間の検出 (= @ricky0123/vad-web、 Silero VAD v5) → 言い終えの判定 (= Smart Turn)
// → 声を文字にして送る。 声の区間の検出と model の本体を含むので重く、 会話を開いた時に初めて読み込まれる。
//
// 返事が鳴っている間も聞き、 人が話し始めたら返事を止める (= 割り込み。 スピーカーの返事はブラウザのエコー除去が
// マイクの音から消す)。 割り込みを切った時は、 鳴っている間は聞かず、 鳴り終えたらまた聞く。 マイク自体は会話を
// 閉じるまで開いたまま (= 聞き直すたびに許可を訊かれないように)。
//
// Adapted from pipecat (https://github.com/pipecat-ai/pipecat), BSD-2-Clause. 詳細 = THIRD_PARTY_NOTICES.md

import { MicVAD } from '@ricky0123/vad-web'
import * as ort from 'onnxruntime-web/wasm'
import { createSmartTurn, judgedPart } from './turn/smartTurn.js'
import { SAMPLE_RATE } from './turn/whisperFeatures.js'
import { createTurnTaker, isUnfinished } from './turnTaker.js'
import { encodeWav } from './wav.js'
import { createWordPeek } from './wordPeek.js'

// Pipecat の既定 (= 声が始まったと見なす長さ、 声の前に付けて送る長さ。
// pipecat の vad_analyzer.py と base_smart_turn.py)
export const VAD_START_MS = 200
export const PRE_SPEECH_MS = 500


const assetBase = () => (typeof __VOICE_ASSET_BASE__ === 'string' ? __VOICE_ASSET_BASE__ : '/')

// Smart Turn の model は、 画面を読み込んでいる間 1 度だけ取って作る (= URL ごと)。
const smartTurns = new Map()
function smartTurnFor(url, fetchModel) {
  if (!smartTurns.has(url)) {
    const made = fetchModel(url).then((model) => createSmartTurn({ ort, model }))
    made.catch(() => smartTurns.delete(url))
    smartTurns.set(url, made)
  }
  return smartTurns.get(url)
}

// 会話を開く。 返す物の close() で閉じる。
//   audioContext   人がボタンを押した手の中で作った AudioContext (= 押した後でないと音を扱えないブラウザがある)
//   stream         同じ手の中で頼んだマイク (= getUserMedia の Promise)
//   turnModelUrl   Smart Turn の model の URL (= 無ければ、 声が途切れた所で送る)
//   settings       間の取り方 (= backend の GET /voice の conversation)
//   fetchModel(url) -> Promise<ArrayBuffer>
//   transcribe(wav) -> Promise<string>   1 つの発話の声 (= WAV の Blob) を文字にする
//   send(text)                           文字にした文を送る
//   isSpeaking() / subscribeSpeaking(listener) -> unsubscribe    返事が鳴っているか
//   interrupt()                          返事を止める (= 返事が鳴っている間に、 人が話し始めた)
//   stopTurn() -> Promise                タブの turn の実行中なら止める (= 話している途中に言葉が取れた。 wordPeek.js)
//   onPhase(phase) / onError(error)
export async function openConversation({
  audioContext, stream, turnModelUrl, settings, fetchModel, transcribe, send, isSpeaking, subscribeSpeaking,
  interrupt, stopTurn, onPhase, onError,
}) {
  const {
    pause_ms: pauseMs, wait_ms: waitMs, resume_ms: resumeMs = 0, unfinished_endings: endings, interrupt: interrupts,
  } = settings
  const base = assetBase()
  // 本体 (= wasm と mjs) は部品の置き場から読む。 複数の thread は、 画面が cross-origin isolated の時しか
  // 使えない (= この画面は違う)。
  ort.env.wasm.wasmPaths = base
  ort.env.wasm.numThreads = 1

  const turn = turnModelUrl ? await smartTurnFor(turnModelUrl, fetchModel) : null
  const peek = stopTurn
    ? createWordPeek({ transcribe: (audio) => transcribe(encodeWav(audio, SAMPLE_RATE)), stopTurn })
    : null
  const taker = createTurnTaker({
    judge: turn ? (audio) => turn.complete(judgedPart(audio, pauseMs)) : null,
    transcribe: (audio) => transcribe(encodeWav(audio, SAMPLE_RATE)),
    send: (text) => {
      peek?.sent()
      return send(text)
    },
    unfinished: (text) => isUnfinished(text, endings),
    pauseMs,
    waitMs,
    resumeMs,
    onPhase,
    onError,
  })
  const vad = await MicVAD.new({
    model: 'v5',
    baseAssetPath: base,
    onnxWASMBasePath: base,
    audioContext,
    startOnLoad: false,
    getStream: () => stream,
    // 返事が鳴る間に聞くのを止めても、 マイクは閉じない
    pauseStream: async () => {},
    resumeStream: async (s) => s,
    // 声が pauseMs 途切れたら、 判定に回す (= 語と語の間の息継ぎでは回さない)
    redemptionMs: pauseMs,
    preSpeechPadMs: PRE_SPEECH_MS,
    minSpeechMs: VAD_START_MS,
    // 話している途中で止めた時も、 そこまでの声を区間として渡す (= 捨てずに、 待っている発話へ足す)
    submitUserSpeechOnPause: true,
    onSpeechStart: () => {
      peek?.start()
      taker.speechStart()
    },
    onFrameProcessed: (_, frame) => peek?.frame(frame),
    // 声が VAD_START_MS 続いた (= 物音ではなく人の声)。 返事が鳴っていれば止める
    onSpeechRealStart: () => { if (interrupts && isSpeaking()) interrupt() },
    onSpeechEnd: (audio) => {
      peek?.end()
      taker.speechEnd(audio)
    },
    onVADMisfire: () => {
      peek?.end()
      taker.misfire()
    },
  })

  let closed = false
  let listening = false
  const follow = async () => {
    if (closed) return
    // 割り込める時は、 返事が鳴っていても聞き続ける
    const speaking = !interrupts && isSpeaking()
    if (speaking && listening) {
      listening = false
      await vad.pause()
      await taker.flush()
    } else if (!speaking && !listening) {
      listening = true
      await vad.start()
      onPhase('listening')
    }
  }
  const unsubscribe = subscribeSpeaking(follow)
  await follow()
  if (isSpeaking()) onPhase('listening')

  return {
    async close() {
      if (closed) return
      closed = true
      unsubscribe()
      peek?.end()
      taker.close()
      try { await vad.destroy() } catch { /* 閉じかけの部品を閉じ直しても何も起きない */ }
    },
  }
}
