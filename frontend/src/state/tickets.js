// 頼みの票の写し (= backend の統合 stream の `tickets` channel の最後の 1 枚)。 真値は backend の票の file と索引で、
// 画面はここに写しを持つだけ。 票の一覧 (= 引き出し)・🎫 の数・タブの一覧の「持つ票の題」 が読む。
// 票の答えの下書きは、 票を読み直しても残すためにここで持つ (= localStorage にも書く)。

import { createStore } from './_store.js'
import { lsGet, lsSet } from '../_common/storage.js'

const DRAFTS_KEY = 'cpc_ticket_drafts'

function loadDrafts() {
  const stored = lsGet(DRAFTS_KEY)
  return stored && typeof stored === 'object' && !Array.isArray(stored) ? stored : {}
}

const INITIAL = {
  loaded: false,   // channel の最初の 1 枚を受けたか (= 受ける前は「票なし」 と区別する)
  tickets: [],     // この機械の票 (= GET /tickets の行 + answer_pending / last_at / last_delivery / attention)
  peers: {},       // もう 1 台ごと: { waiting: N } か { unreadable: true }
  answerDrafts: loadDrafts(),  // { [票の id]: { askedAt, text } } 答えの下書き (= どの問いへの下書きか持つ)
}

const store = createStore(INITIAL, { name: 'tickets' })

export const getSnapshot = () => store.getSnapshot()
export const subscribe = (listener) => store.subscribe(listener)

/** channel の 1 枚を取り込む。 形が違う物は捨てる (= 古い画面と新しい backend の食い違いで落ちない)。 */
export function applyTicketsSnapshot(data) {
  if (!data || typeof data !== 'object' || !Array.isArray(data.tickets)) return
  const peers = data.peers && typeof data.peers === 'object' ? data.peers : {}
  store.setState(prev => ({ ...prev, loaded: true, tickets: data.tickets, peers }))
}

/** 票の答えの下書きを置く (= 空の文は消す)。 `askedAt` はその下書きが向いている問いの時刻。 */
export function setAnswerDraft(ticket, askedAt, text) {
  store.setState(prev => {
    const answerDrafts = { ...prev.answerDrafts }
    if (text) answerDrafts[ticket] = { askedAt, text }
    else delete answerDrafts[ticket]
    lsSet(DRAFTS_KEY, answerDrafts)
    return { ...prev, answerDrafts }
  })
}
