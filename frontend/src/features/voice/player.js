// 声にする文を、 順に音にして、 順に鳴らす (= 通信と音の出し方は外から渡される)。
//
// 返事 1 本は、 backend が「声にする文」 の並びに切る。 音は 1 文ずつ作ってもらい、 1 文目が届いた時点で
// 鳴らし始める。 作る方は鳴らす方より先へ進む (= 1 文を鳴らしている間に、 次の文の音が出来ている) が、
// 同時に頼むのは 1 文だけ (= 音声合成は重い)。
//
// 止める (= stop) と、 鳴っている音を切り、 待っている文を全部捨てる。 頼んである通信も捨てる。
//
// deps:
//   utterances(sid, text, signal) -> Promise<[{ mark, text }]>   返事の文 → 声にする文の並び
//   sound(sid, utterance, signal) -> Promise<ArrayBuffer>        1 文 → 音
//   play(sid, sound) -> { done: Promise<void>, stop() }          音を鳴らす
//   onError(sid, error)                                          鳴らせなかった (= その返事の残りは捨てる)
//   onPlayed(sid)                                                1 文が鳴り終えた
//   onBusy(sid, busy)                                            鳴らす物を抱え始めた / 全部鳴り終えた (= 止めた時も)
//                                                                (= 合成を待っている間も「抱えている」 に数える)

export function createPlayer({ utterances, sound, play, onError = () => {}, onPlayed = () => {}, onBusy = () => {} }) {
  const tabs = new Map()   // sid -> { run, abort, making, playing, current, pending: 抱えている返事の数 }
  const tab = (sid) => {
    let t = tabs.get(sid)
    if (!t) {
      t = { run: 0, abort: new AbortController(), making: Promise.resolve(), playing: Promise.resolve(), current: null, pending: 0 }
      tabs.set(sid, t)
    }
    return t
  }

  function say(sid, text) {
    const t = tab(sid)
    const run = t.run
    const signal = t.abort.signal
    const live = () => t.run === run
    // 返事 1 本ごとの失敗の印: 1 文が鳴らせなければ、 その返事の残りは作らず、 鳴らさない。
    const reply = { failed: false }
    const fail = (error) => {
      if (!live() || reply.failed) return
      reply.failed = true
      onError(sid, error)
    }
    t.pending += 1
    if (t.pending === 1) onBusy(sid, true)

    t.making = t.making.then(async () => {
      if (!live()) return
      let list
      try {
        list = await utterances(sid, text, signal)
      } catch (error) {
        fail(error)
        return
      }
      for (const utterance of list) {
        if (!live() || reply.failed) return
        // 音を作る約束を、 鳴らす列に先に並べる (= 鳴らす順は、 並べた順)。
        const made = sound(sid, utterance, signal)
        made.catch(() => {})
        t.playing = t.playing.then(async () => {
          if (!live() || reply.failed) return
          try {
            const data = await made
            if (!live() || reply.failed) return
            t.current = play(sid, data)
            await t.current.done
            t.current = null
            if (live()) onPlayed(sid)
          } catch (error) {
            t.current = null
            fail(error)
          }
        })
        // 次の文を頼むのは、 この文の音が出来てから (= 同時に頼むのは 1 文)。
        try { await made } catch { return }
      }
    })
    // この返事の文を作り終えた時点の「鳴らす列」 の終わりが、 この返事の最後の 1 文 (= 後の返事は、 まだ並んでいない)。
    t.making.then(() => t.playing).then(() => {
      if (!live()) return
      t.pending -= 1
      if (t.pending === 0) onBusy(sid, false)
    })
  }

  function stop(sid) {
    const t = tab(sid)
    t.run += 1
    t.abort.abort()
    t.abort = new AbortController()
    if (t.current) { try { t.current.stop() } catch { /* 鳴り終えた音を止めても何も起きない */ } }
    t.current = null
    t.making = Promise.resolve()
    t.playing = Promise.resolve()
    if (t.pending > 0) { t.pending = 0; onBusy(sid, false) }
  }

  // test 用: そのタブの、 並んでいる分が全部済むまで待つ。
  async function idle(sid) {
    const t = tab(sid)
    let making, playing
    do {
      making = t.making
      playing = t.playing
      await making
      await playing
    } while (making !== t.making || playing !== t.playing)
  }

  return { say, stop, idle }
}
