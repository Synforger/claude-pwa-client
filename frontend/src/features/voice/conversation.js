// 会話の配線: マイク → 声の区間の検出 (= @ricky0123/vad-web、 Silero VAD v5) → 言い終えの判定 (= Smart Turn)
// → 声を文字にして送る。 声の区間の検出と model の本体を含むので重く、 会話を開いた時に初めて読み込まれる。
//
// 返事が鳴っている間は聞かない (= スピーカーの返事を人の声と取り違えて、 返事に返事をし続けないように)。
// 鳴り終えたら、 また聞く。 マイク自体は会話を閉じるまで開いたまま (= 聞き直すたびに許可を訊かれないように)。
//
// Adapted from pipecat (https://github.com/pipecat-ai/pipecat), BSD-2-Clause. 詳細 = THIRD_PARTY_NOTICES.md

import { MicVAD } from '@ricky0123/vad-web'
import * as ort from 'onnxruntime-web/wasm'
import { createSmartTurn } from './turn/smartTurn.js'
import { SAMPLE_RATE } from './turn/whisperFeatures.js'
import { createTurnTaker, VAD_STOP_MS } from './turnTaker.js'
import { encodeWav } from './wav.js'

// Pipecat の既定 (= 声が始まったと見なす長さ、 声の前に付けて送る長さ。 pipecat の vad_analyzer.py と
// base_smart_turn.py)
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
//   fetchModel(url) -> Promise<ArrayBuffer>
//   hear(wav) -> Promise<void>        1 つの発話の声 (= WAV の Blob) を、 文字にして送る
//   isSpeaking() / subscribeSpeaking(listener) -> unsubscribe    返事が鳴っているか
//   onPhase(phase) / onError(error)
export async function openConversation({
  audioContext, stream, turnModelUrl, fetchModel, hear, isSpeaking, subscribeSpeaking, onPhase, onError,
}) {
  const base = assetBase()
  // 本体 (= wasm と mjs) は部品の置き場から読む。 複数の thread は、 画面が cross-origin isolated の時しか
  // 使えない (= この画面は違う)。
  ort.env.wasm.wasmPaths = base
  ort.env.wasm.numThreads = 1

  const turn = turnModelUrl ? await smartTurnFor(turnModelUrl, fetchModel) : null
  const taker = createTurnTaker({
    judge: turn ? (audio) => turn.complete(audio) : null,
    hear: (audio) => hear(encodeWav(audio, SAMPLE_RATE)),
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
    // Smart Turn を持つ時は、 0.2 秒の途切れで判定に回す。 持たない時は vad-web の既定の長さで送る
    ...(turn ? { redemptionMs: VAD_STOP_MS } : {}),
    preSpeechPadMs: PRE_SPEECH_MS,
    minSpeechMs: VAD_START_MS,
    // 話している途中で止めた時も、 そこまでの声を区間として渡す (= 捨てずに、 待っている発話へ足す)
    submitUserSpeechOnPause: true,
    onSpeechStart: () => taker.speechStart(),
    onSpeechEnd: (audio) => taker.speechEnd(audio),
    onVADMisfire: () => taker.misfire(),
  })

  let closed = false
  let listening = false
  const follow = async () => {
    if (closed) return
    const speaking = isSpeaking()
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
      taker.close()
      try { await vad.destroy() } catch { /* 閉じかけの部品を閉じ直しても何も起きない */ }
    },
  }
}
