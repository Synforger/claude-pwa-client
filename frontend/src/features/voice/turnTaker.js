// 会話の順番 (= 人が言い終えたら、 その声を送る)。 マイクも model も持たず、 渡された関数で判定と送りを行う。
//
// 写した前例: Pipecat の Smart Turn の使い方 (= pipecat の audio/turn/smart_turn/base_smart_turn.py)。
//   - 声の区間の検出が「声が途切れた」 と言ったら、 その時までの声を Smart Turn に見せる
//   - 言い終えた → 文字にして送る
//   - まだ考え中 → 続きを待つ。 続きが来ないまま、 声が途切れてから waitMs たったら送る
//   - 続きが来たら、 前の声とつなげて 1 つの発話にする
// Smart Turn を持たない時は、 声の区間の検出が「途切れた」 と言った所で送る。
//
// Pipecat に足した物:
//   - 声の区間が終わった時点で、 判定と並べて文字にし始める (= 判定を待つ間・続きを待つ間に文字が出来ている)
//   - 文字にした文が言いさし (= 読点や「えーと」 で終わる) なら、 言い終えた判定でも送らずに続きを待つ
//   - 文字にしている間に続きを話し始めたら、 その発話は送らずに続きとつなげる
//   - 言い終えた発話も、 送る前に resumeMs 待つ。 その間に続きを話し始めたら、 送らずに続きとつなげる (= Smart Turn は
//     長い発話の途中の間でも「言い終えた」 と出すことがある)
//
// deps:
//   judge(audio) -> Promise<boolean> | null    言い終えたか (= null なら判定しない)
//   transcribe(audio) -> Promise<string>       1 つの発話の声を文字にする (= 声でなければ空の文)
//   send(text)                                 文字にした文を送る
//   unfinished(text) -> boolean                言いさしか (= 送らずに続きを待つ)
//   pauseMs / waitMs                           声の区間の検出が「途切れた」 と言うまでの無音 / 送るまで待つ無音
//   resumeMs                                   言い終えた発話を送る前に待つ時間 (= 0 なら待たない)
//   onPhase(phase)                             'listening' / 'talking' / 'judging' / 'hearing'
//   onError(error)                             判定か文字にするのが失敗した (= 判定の失敗は送り、 文字の失敗は捨てる)
//
// Adapted from pipecat (https://github.com/pipecat-ai/pipecat), BSD-2-Clause. 詳細 = THIRD_PARTY_NOTICES.md

export function createTurnTaker({
  judge, transcribe, send, unfinished = () => false, pauseMs, waitMs, resumeMs = 0,
  onPhase = () => {}, onError = () => {}, timers = globalThis, now = () => Date.now(),
}) {
  let pieces = []        // この発話の声 (= 区間ごとの Float32Array)
  let writing = null     // 文字にしている / した結果 (= { count: 文字にした区間の数, text: Promise<string> })
  let endedAt = 0        // 最後の区間が終わった時刻 (= 声が途切れてから pauseMs 後)
  let wait = null        // 続きを待つ時計
  let generation = 0     // 新しい声が来るたびに進む (= 古い判定・古い文字の答えで送らない)
  let hearing = 0        // 文字にしている発話の数
  let closed = false

  const idlePhase = () => onPhase(hearing > 0 ? 'hearing' : 'listening')
  const clearWait = () => { if (wait) { timers.clearTimeout(wait); wait = null } }

  // 続きを待つ (= 声が途切れてから waitMs たったら送る)
  function holdUntilQuiet() {
    clearWait()
    const left = Math.max(0, waitMs - pauseMs - (now() - endedAt))
    wait = timers.setTimeout(() => { wait = null; finish({ force: true }) }, left)
    idlePhase()
  }

  // 今の区間までを文字にする (= 同じ区間の数なら、 前に頼んだ結果を使う)
  function write() {
    const count = pieces.length
    if (writing?.count !== count) {
      const text = transcribe(join(pieces.slice(0, count)))
      text.catch(() => {})   // 失敗は、 その結果を待つ finish が受ける
      writing = { count, text }
    }
    return writing
  }

  // 待っている発話を文字にして送る。 force = 待ち切った (= 言いさしでも送る)
  async function finish({ force = false } = {}) {
    clearWait()
    if (!pieces.length || closed) return
    const asked = generation
    const { count, text: written } = write()
    let text
    hearing += 1
    onPhase('hearing')
    try {
      text = await written
    } catch (error) {
      if (!closed) onError(error)
      if (asked === generation) { pieces = pieces.slice(count); writing = null }
      return
    } finally {
      hearing -= 1
    }
    if (closed) return
    // 文字にしている間に続きを話し始めた: 送らずに、 続きとつなげて決め直す
    if (asked !== generation) return
    if (!force && text && unfinished(text)) { holdUntilQuiet(); return }
    if (!force && text && resumeMs > 0) { holdForResume(count, text); return }
    commit(count, text)
  }

  // 文字にした発話を送る (= 送った区間を、 待っている声から外す)
  function commit(count, text) {
    pieces = pieces.slice(count)
    writing = null
    if (text) send(text)
    idlePhase()
  }

  // 言い終えた発話を、 送る前に resumeMs だけ待つ (= その間に声が始まれば speechStart が待ちを止め、 続きとつなげる)
  function holdForResume(count, text) {
    clearWait()
    wait = timers.setTimeout(() => { wait = null; if (!closed) commit(count, text) }, resumeMs)
    idlePhase()
  }

  return {
    // 声が始まった (= 待っている続きが来た)
    speechStart() {
      if (closed) return
      clearWait()
      generation += 1
      onPhase('talking')
    },
    // 声の区間が終わった (= 声が pauseMs 途切れた)。 audio = その区間の声 (= 16kHz の Float32Array)
    async speechEnd(audio) {
      if (closed) return
      pieces.push(audio)
      endedAt = now()
      const asked = ++generation
      write()
      if (!judge) { await finish(); return }
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
      holdUntilQuiet()
    },
    // 声が始まったと思ったが、 短すぎて声ではなかった (= 待っている発話が在れば、 待ち直す)
    misfire() {
      if (closed) return
      if (pieces.length && !wait) holdUntilQuiet()
      else idlePhase()
    },
    // 聞くのを止めた (= 返事が鳴り始めた時)。 待っている発話は、 そこで送る
    flush() { return finish({ force: true }) },
    // 会話を閉じた。 待っている発話は捨てる
    close() {
      closed = true
      clearWait()
      pieces = []
      writing = null
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

// 言いさしか (= 読点・三点で終わる、 または文末の句点を外して endings の語で終わる)
export function isUnfinished(text, endings) {
  const said = String(text || '').trim()
  if (!said) return false
  const bare = said.replace(/[。．.!！?？\s]+$/u, '')
  return endings.some((ending) => said.endsWith(ending) || (bare && bare.endsWith(ending)))
}
