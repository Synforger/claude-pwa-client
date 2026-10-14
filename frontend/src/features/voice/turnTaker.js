// 会話の順番 (= 人が言い終えたら、 その声を送る)。 マイクも model も持たず、 渡された関数で判定と送りを行う。
//
// 写した前例: Pipecat の Smart Turn の使い方 (= pipecat の audio/turn/smart_turn/base_smart_turn.py)。
//   - 声の区間の検出が「声が 0.2 秒途切れた」 と言ったら、 その時までの声を Smart Turn に見せる
//   - 言い終えた → すぐ送る
//   - まだ考え中 → 続きを待つ。 続きが来ないまま、 声が途切れてから 3 秒たったら送る
//   - 続きが来たら、 前の声とつなげて 1 つの発話にする
// Smart Turn を持たない時は、 声の区間の検出が「途切れた」 と言った所で送る。
//
// deps:
//   judge(audio) -> Promise<boolean> | null    言い終えたか (= null なら判定しない)
//   hear(audio) -> Promise<void>               1 つの発話の声を、 文字にして送る
//   onPhase(phase)                             'listening' / 'talking' / 'judging' / 'hearing'
//   onError(error)                             判定か送りが失敗した (= その発話は捨てる)
//
// Adapted from pipecat (https://github.com/pipecat-ai/pipecat), BSD-2-Clause. 詳細 = THIRD_PARTY_NOTICES.md

// Pipecat の既定 (= 声の区間の検出の「途切れた」 までの時間と、 言い終えを待つ上限の無音)
export const VAD_STOP_MS = 200
export const STOP_MS = 3000

export function createTurnTaker({ judge, hear, onPhase = () => {}, onError = () => {}, timers = globalThis }) {
  let pieces = []      // この発話の声 (= 区間ごとの Float32Array)
  let wait = null      // 続きを待つ時計
  let generation = 0   // 新しい声が来るたびに進む (= 古い判定の答えを捨てる)
  let hearing = 0      // 文字にしている発話の数
  let closed = false

  const idlePhase = () => onPhase(hearing > 0 ? 'hearing' : 'listening')
  const clearWait = () => { if (wait) { timers.clearTimeout(wait); wait = null } }

  async function finish() {
    clearWait()
    if (!pieces.length || closed) return
    const audio = join(pieces)
    pieces = []
    generation += 1
    hearing += 1
    onPhase('hearing')
    try {
      await hear(audio)
    } catch (error) {
      if (!closed) onError(error)
    } finally {
      hearing -= 1
      if (!closed) idlePhase()
    }
  }

  return {
    // 声が始まった (= 待っている続きが来た)
    speechStart() {
      if (closed) return
      clearWait()
      generation += 1
      onPhase('talking')
    },
    // 声の区間が終わった (= 声が 0.2 秒途切れた)。 audio = その区間の声 (= 16kHz の Float32Array)
    async speechEnd(audio) {
      if (closed) return
      pieces.push(audio)
      if (!judge) { await finish(); return }
      const asked = ++generation
      onPhase('judging')
      let complete
      try {
        complete = await judge(join(pieces))
      } catch (error) {
        // 判定できない時は、 言い終えたものとして送る (= 送られずに止まるより、 早く送る方を採る)
        if (!closed) onError(error)
        complete = true
      }
      if (closed || asked !== generation) return
      if (complete) { await finish(); return }
      clearWait()
      wait = timers.setTimeout(() => { wait = null; finish() }, STOP_MS - VAD_STOP_MS)
      idlePhase()
    },
    // 声が始まったと思ったが、 短すぎて声ではなかった (= 待っている発話が在れば、 待ち直す)
    misfire() {
      if (closed) return
      if (pieces.length && !wait) wait = timers.setTimeout(() => { wait = null; finish() }, STOP_MS - VAD_STOP_MS)
      idlePhase()
    },
    // 聞くのを止めた (= 返事が鳴り始めた時)。 待っている発話は、 そこで送る
    flush() { return finish() },
    // 会話を閉じた。 待っている発話は捨てる
    close() {
      closed = true
      clearWait()
      pieces = []
    },
  }
}

// 区間ごとの声を 1 つにつなぐ
export function join(pieces) {
  if (pieces.length === 1) return pieces[0]
  const out = new Float32Array(pieces.reduce((n, p) => n + p.length, 0))
  let at = 0
  for (const p of pieces) { out.set(p, at); at += p.length }
  return out
}
