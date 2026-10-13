// 声 (= agent の返事を音で聞く) の store。
//
// shape (= どれもタブの id ごと):
//   available: そのタブの agent が声を持つか (= backend `GET /sessions/{sid}/voice` の写し。 訊くまでは無い)
//   marks:     その agent の言い方の印の名前 (= 同じ GET の写し。 吹き出しの表示から印を外すのに使う)
//   on:        このタブの返事を鳴らすか (= 上部の 🔊 の ON / OFF。 画面を読み込み直すと OFF に戻る:
//              音は、 人がボタンを押した後でないと鳴らせない)
//   error:     最後に鳴らせなかった理由の文 (= 次に鳴った時と、 OFF にした時に消える)

import { createStore } from './_store.js'

const INITIAL = { available: {}, marks: {}, on: {}, error: {} }

const store = createStore(INITIAL, { name: 'voice' })

export const getSnapshot = () => store.getSnapshot()
export const subscribe = (listener) => store.subscribe(listener)

function setFor(field, sid, value) {
  store.setState(prev => {
    const had = Object.prototype.hasOwnProperty.call(prev[field], sid)
    if (value == null) {
      if (!had) return prev
      const rest = { ...prev[field] }
      delete rest[sid]
      return { ...prev, [field]: rest }
    }
    if (had && prev[field][sid] === value) return prev
    return { ...prev, [field]: { ...prev[field], [sid]: value } }
  })
}

export function setVoiceAvailable(sid, available) { setFor('available', sid, !!available) }
export function setVoiceMarks(sid, marks) {
  const next = Array.isArray(marks) ? marks.filter(name => typeof name === 'string') : []
  const had = store.getSnapshot().marks[sid]
  // 中身が同じなら配列を差し替えない (= 読む側の再描画を起こさない)。
  if (had ? had.length === next.length && had.every((name, i) => name === next[i]) : next.length === 0) return
  setFor('marks', sid, next.length ? next : null)
}
export function setVoiceOn(sid, on) { setFor('on', sid, on ? true : null) }
export function setVoiceError(sid, text) { setFor('error', sid, text || null) }

// test 用: store を INITIAL に戻す (= module singleton なので各 test の beforeEach で呼ぶ)。
export function _resetForTest() {
  store.setState(() => INITIAL)
}
