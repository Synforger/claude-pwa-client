// 届いた event のうち、 どれを声にするかを決める (= 音も通信も持たない)。
//
// 声にするのは agent の返事の文と、 ツールの呼び出しに付いた説明文 (= 「今何をしているか」 の 1 行)。
// thinking と、 説明文の無いツールの呼び出しは声にしない。
//
// 鳴らすのは「新しく届いた物」 だけ:
//   - 履歴の読み込み (= タブを開いた時の GET) で届いた物は、 聞いた事にして鳴らさない
//   - ON にした時点までに届いていた物は鳴らさない (= 時刻は event が運ぶ backend の時刻だけで比べる)
//   - 同じ物が 2 度届いても 1 度だけ鳴らす (= 繋ぎ直しで、 同じ event が流れ直すことがある)

import { MAX_MESSAGES } from '../../constants.js'

// 1 つのタブで覚えておく「聞いた物」 の数。 超えた分は古い順に忘れる (= ON にする前の物は、 忘れても時刻で
// 弾かれる)。 画面が 1 つのタブに持つ吹き出しの数に、 吹き出し 1 つの候補 (= 文 1 つとツールの説明文) の
// 見込みを掛けた数。
const PARTS_PER_MESSAGE = 10
export const MAX_HEARD = MAX_MESSAGES * PARTS_PER_MESSAGE

// event から、 声にする候補を取り出す。 key は、 同じ物をもう 1 度鳴らさないための名前。
export function speechParts(event) {
  if (!event || event.type !== 'assistant' || event.parent_tool_use_id) return []
  const content = event.message?.content
  if (!Array.isArray(content)) return []
  const parts = []
  const text = content.filter(b => b?.type === 'text').map(b => b.text || '').join('')
  if (text.trim() && event.uuid) parts.push({ key: `${event.uuid}:text`, text })
  for (const block of content) {
    if (block?.type !== 'tool_use' || !block.id) continue
    const description = typeof block.input?.description === 'string' ? block.input.description.trim() : ''
    if (description) parts.push({ key: `tool:${block.id}`, text: description })
  }
  return parts
}

// isOn(sid) が真のタブの、 新しく届いた物を say(sid, text) へ渡す。
export function createListener({ isOn, say }) {
  const tabs = new Map()   // sid -> { heard: Set<key>, lastTs: number, since: number | null }
  const tab = (sid) => {
    let t = tabs.get(sid)
    if (!t) { t = { heard: new Set(), lastTs: 0, since: null }; tabs.set(sid, t) }
    return t
  }

  return {
    // ON にした時に呼ぶ: これより前に届いていた物は鳴らさない。
    start(sid) { const t = tab(sid); t.since = t.lastTs },
    stop(sid) { tab(sid).since = null },
    // 届いた event を 1 つ見る。 history = 履歴の読み込みで届いた物か。
    observe(sid, event, { history = false } = {}) {
      const parts = speechParts(event)
      if (!parts.length) return
      const t = tab(sid)
      const ts = typeof event.ts === 'number' ? event.ts : null
      const fresh = !history && ts != null && t.since != null && ts > t.since && isOn(sid)
      for (const part of parts) {
        if (t.heard.has(part.key)) continue
        t.heard.add(part.key)
        if (t.heard.size > MAX_HEARD) t.heard.delete(t.heard.values().next().value)
        if (fresh) say(sid, part.text)
      }
      if (ts != null && ts > t.lastTs) t.lastTs = ts
    },
  }
}
