// 話している途中の言葉: 話している間、 PEEK_MS ごとにそこまでの声を文字にしてみて、 言葉が取れたらタブの turn を
// 止める (= 話し終えるのを待たずに。 あくびや物音は言葉にならないので止めない)。 止めるのは送るまでに 1 回だけ。
// 途中の文字は止めるかを決めるためだけに使い、 送る文にはしない (= 送る文は、 言い終えた発話を 1 回で文字にした物)。
//
//   transcribe(audio) -> Promise<string>   声 (= 16kHz の Float32Array) を文字にする
//   stopTurn() -> Promise                   タブの turn の実行中なら止める
import { join } from './turnTaker.js'

// 話している途中の声を文字にしてみる間隔 (= 言葉が取れるまで)
export const PEEK_MS = 500

export function createWordPeek({ transcribe, stopTurn, everyMs = PEEK_MS }) {
  let heard = []        // この声の区間の声 (= 枠ごとの Float32Array)
  let timer = null
  let stopped = false   // 送るまでの発話で、 もう turn を止めたか
  let trying = false

  function end() {
    clearInterval(timer)
    timer = null
    heard = []
  }

  async function tryWords() {
    if (stopped || trying || !heard.length) return
    trying = true
    try {
      const text = await transcribe(join(heard))
      if (text && !stopped) {
        stopped = true
        end()
        await stopTurn()
      }
    } catch {
      // 途中の聞き取りの失敗では止めない (= 送る文は、 言い終えた発話を別に聞き取る)
    } finally {
      trying = false
    }
  }

  return {
    // 声の区間が始まった
    start() {
      end()
      if (!stopped) timer = setInterval(tryWords, everyMs)
    },
    // 1 枠の声 (= 区間の間だけ溜める。 枠は検出の部品が使い回すので写す)
    frame(f) {
      if (timer) heard.push(new Float32Array(f))
    },
    // 声の区間が終わった (= 物音だった時も)
    end,
    // 発話を送った (= 次の発話では、 また止める)
    sent() {
      stopped = false
    },
  }
}
