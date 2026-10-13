// 声 (= agent の返事を音で聞く) の store。
//
// shape (= どれもタブの id ごと):
//   available: そのタブの agent が声を持つか (= backend `GET /sessions/{sid}/voice` の写し。 訊くまでは無い)
//   on:        このタブの返事を鳴らすか (= 上部の 🔊 の ON / OFF。 画面を読み込み直すと OFF に戻る:
//              音は、 人がボタンを押した後でないと鳴らせない)
//   error:     最後に鳴らせなかった理由の文 (= 次に鳴った時と、 OFF にした時に消える)

import { createStore } from './_store.js'

const INITIAL = { available: {}, on: {}, error: {} }

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
export function setVoiceOn(sid, on) { setFor('on', sid, on ? true : null) }
export function setVoiceError(sid, text) { setFor('error', sid, text || null) }

// test 用: store を INITIAL に戻す (= module singleton なので各 test の beforeEach で呼ぶ)。
export function _resetForTest() {
  store.setState(() => INITIAL)
}
