// 使う時だけ起こす声の engine (= backend の voice.engine_service) の今を、 🔊 が入っている間だけ読み直して store に
// 写す (= GET /sessions/<sid>/voice/engine)。 VoiceButtons が 🔊 を入れた時に始め、 切った時・タブが替わった時・
// 外れた時に止める。 起き切るまでは 2 秒ごと、 起きている間は 15 秒ごとに読む。 返ってから次を打ち、 止めた後に
// 返った答えは捨てる。 読みが失敗しても engine の値の他には触らない。 engine を扱わないタブ (= null) と、 この口を
// 持たない backend (= 404) では読むのをやめる。 画面が裏に回っている間は打たない。

import { apiFetch } from '../../transport/http.ts'
import { setVoiceEngine } from '../../state/voice.js'

export const SOON_MS = 2000
export const LATER_MS = 15000

// そのタブの engine の今。 → 'ready' / 'waking' / 'asleep' / 'failed'、 扱わないなら null。 読めなければ throw。
export async function fetchEngine(sid) {
  const r = await apiFetch(`/sessions/${encodeURIComponent(sid)}/voice/engine`)
  if (r.status === 404) return null
  if (!r.ok) throw new Error(`voice engine: HTTP ${r.status}`)
  const body = await r.json()
  return typeof body?.engine === 'string' ? body.engine : null
}

// sid の engine を読み直し始める。 → 止める関数 (= 止めると store の値も消す)。
export function watchEngine(sid, {
  fetchState = fetchEngine, setEngine = setVoiceEngine, schedule = setTimeout, cancel = clearTimeout,
  isHidden = () => typeof document !== 'undefined' && document.hidden,
} = {}) {
  let stopped = false
  let timer = null
  const next = (ms) => { if (!stopped) timer = schedule(tick, ms) }
  async function tick() {
    timer = null
    if (stopped) return
    if (isHidden()) { next(SOON_MS); return }
    let state
    try {
      state = await fetchState(sid)
    } catch {
      next(SOON_MS)
      return
    }
    if (stopped) return
    setEngine(sid, state)
    if (state === null) return
    next(state === 'ready' ? LATER_MS : SOON_MS)
  }
  tick()
  return () => {
    stopped = true
    if (timer !== null) cancel(timer)
    setEngine(sid, null)
  }
}
