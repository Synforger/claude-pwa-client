// 票の画面の下の欄に何を出すか (= 設計の「3 の下の欄」 の表) を、 票を読んだ結果から決める純関数。
// 欄は 1 つに決めず、 重なり得る物 (= 返事待ちと、 前の答えが届く途中) は別の項目で返す。

const WAITING = 'waiting-operator'
const CLOSED = 'closed'
const UNSETTLED = ['refused', 'unconfirmed']

const lastOf = (entries, kind) => {
  for (let index = entries.length - 1; index >= 0; index--) {
    if (entries[index].kind === kind) return entries[index]
  }
  return null
}

/** `detail` は `GET /tickets/{id}/answer` の答え。 → {
 *   noHolder: 持つタブが無い (閉じていない) か、
 *   asked: 答えを待つ問いの件 (= 返事待ちで、 持つタブが居る時だけ。 無ければ null)、
 *   askedWithoutHolder: 返事待ちだが持つタブが無い時の問いの件 (= 読めるだけで答えは出せない)、
 *   hasRecommend: その問いが推奨を持つか、
 *   pending: 届く途中の答えが向いた問いの時刻の並び、
 *   closedPending: 届く途中の答えを持つ票が閉じているか、
 *   problem: 最後の届けが届かなかった / 届いたか分からない時の `refused` / `unconfirmed`、 無ければ null }。 */
export function lowerArea(detail) {
  const entries = Array.isArray(detail.entries) ? detail.entries : []
  const closed = detail.status === CLOSED
  const noHolder = !closed && !detail.holder
  const waiting = detail.status === WAITING
  const askedLine = waiting ? lastOf(entries, 'asked') : null
  const delivery = detail.last_delivery
  const pendingKeys = Array.isArray(detail.answer_pending) ? detail.answer_pending : []
  return {
    noHolder,
    asked: askedLine && detail.holder ? askedLine : null,
    askedWithoutHolder: askedLine && !detail.holder ? askedLine : null,
    hasRecommend: !!(askedLine && askedLine.recommend),
    pending: pendingKeys,
    closedPending: closed && pendingKeys.length > 0,
    problem: delivery && UNSETTLED.includes(delivery.result) && !delivery.followed ? delivery.result : null,
  }
}

/** 押し直しの成功の扱い: 返事が網で落ちて押し直したら、 前の 1 回目は受かっている。 読み直した票の最後の `answered` が
 *  自分の送った問い (`askedAt`) への答えなら、 受かっている。 */
export function answerLanded(detail, askedAt) {
  const entries = Array.isArray(detail.entries) ? detail.entries : []
  const last = lastOf(entries, 'answered')
  return !!last && last.asked_at === askedAt
}

/** 下書きが、 今の問いの物か。 今の問いが替わっていて下書きが残っていれば「前の問いへの下書き」 になる。 */
export function draftState(draft, askedAt) {
  if (!draft || !draft.text) return 'none'
  return !askedAt || draft.askedAt === askedAt ? 'current' : 'previous'
}
