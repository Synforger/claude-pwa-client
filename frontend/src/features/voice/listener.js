// 届いた event のうち、 どれを声にするかを決める (= 音も通信も持たない)。
//
// 声にするのは agent の返事の文 (= ツールの合間に書いた文も含む)。 thinking と、 ツールの呼び出し (= その説明文も)
// は声にしない (= 何をしているかは画面で見えるので、 声では言わない)。
//
// 鳴らすのは「新しく届いた物」 だけ:
//   - 履歴の読み込み (= タブを開いた時の GET) で届いた物は、 聞いた事にして鳴らさない
//   - ON にした時点までに届いていた物は鳴らさない (= 時刻は event が運ぶ backend の時刻だけで比べる)
//   - 同じ物が 2 度届いても 1 度だけ鳴らす (= 繋ぎ直しで、 同じ event が流れ直すことがある)
//   - 会話で新しい発話を送った後は、 タブの記録にその発話が載る (= 新しい turn が始まる) まで鳴らさない
//     (= agent が新しい発話を考えている間に、 前の返事の続きが鳴らないように)
//   - 新しい返事が届いたら、 前の返事の鳴り残しを止めてから鳴らす (= cut(sid)。 同じ turn の中のツールの合間の文でも。
//     いつも一番新しい返事を聞く)

import { MAX_MESSAGES } from '../../constants.js'

// 1 つのタブで覚えておく「聞いた物」 の数。 超えた分は古い順に忘れる (= ON にする前の物は、 忘れても時刻で
// 弾かれる)。 画面が 1 つのタブに持つ吹き出しの数に、 吹き出し 1 つの候補の見込みを掛けた数。
const PARTS_PER_MESSAGE = 10
export const MAX_HEARD = MAX_MESSAGES * PARTS_PER_MESSAGE

// event から、 声にする候補を取り出す。 key は、 同じ物をもう 1 度鳴らさないための名前。
export function speechParts(event) {
  if (!event || event.type !== 'assistant' || event.parent_tool_use_id) return []
  const content = event.message?.content
  if (!Array.isArray(content)) return []
  const text = content.filter(b => b?.type === 'text').map(b => b.text || '').join('')
  return text.trim() && event.uuid ? [{ key: `${event.uuid}:text`, text }] : []
}

// isOn(sid) が真のタブの、 新しく届いた物を say(sid, text) へ渡す。 2 つ目からの返事の前に cut(sid) を呼ぶ。
export function createListener({ isOn, say, cut = () => {} }) {
  // sid -> { heard: Set<key>, lastTs, since: number | null, holding, said: もう返事を鳴らしたか }
  const tabs = new Map()
  const tab = (sid) => {
    let t = tabs.get(sid)
    if (!t) { t = { heard: new Set(), lastTs: 0, since: null, holding: false, said: false }; tabs.set(sid, t) }
    return t
  }

  return {
    // ON にした時に呼ぶ: これより前に届いていた物は鳴らさない。
    start(sid) { const t = tab(sid); t.since = t.lastTs },
    stop(sid) { const t = tab(sid); t.since = null; t.holding = false },
    // 会話で新しい発話を送った時に呼ぶ: その発話で次の turn が始まるまで、 届いた返事を鳴らさない。
    holdUntilNextTurn(sid) { tab(sid).holding = true },
    // 届いた event を 1 つ見る。 history = 履歴の読み込みで届いた物か。
    observe(sid, event, { history = false } = {}) {
      if (event?.type === 'user_message' && !history) tab(sid).holding = false
      const parts = speechParts(event)
      if (!parts.length) return
      const t = tab(sid)
      const ts = typeof event.ts === 'number' ? event.ts : null
      const fresh = !history && ts != null && t.since != null && ts > t.since && isOn(sid) && !t.holding
      for (const part of parts) {
        if (t.heard.has(part.key)) continue
        t.heard.add(part.key)
        if (t.heard.size > MAX_HEARD) t.heard.delete(t.heard.values().next().value)
        if (!fresh) continue
        if (t.said) cut(sid)
        t.said = true
        say(sid, part.text)
      }
      if (ts != null && ts > t.lastTs) t.lastTs = ts
    },
  }
}
