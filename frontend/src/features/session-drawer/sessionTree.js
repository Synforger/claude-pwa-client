// 会話の一覧の親子の並び。 フォークのタブと子のタブ (= parent_id を持つ) を親の直下に字下げして並べ、
// 畳んだ親の下は出さない。 親は畳んで始まり、 開いた親を端末ごとに覚える (= その端末の一覧の見え方で、
// 他の端末に合わせる物ではない)。

import { lsGet, lsSet } from '../../_common/storage.js'

export const OPENED_KEY = 'cpc.drawer.opened'

// 並びは渡された順 (= 最終活動の降順) を保つ。 親が一覧に居ない孤児はトップレベル扱い。
// 1 行 = { session, depth, children (= 直下の子の数), folded (= 畳まれている), hidden (= 畳んで隠れた数),
//          hiddenTabs (= 畳んで隠れたタブ) }
export function sessionTree(sorted, opened) {
  const ids = new Set(sorted.map(s => s.id))
  const below = {}
  for (const s of sorted) {
    const key = (s.parent_id && ids.has(s.parent_id)) ? s.parent_id : '__root__'
    if (!below[key]) below[key] = []
    below[key].push(s)
  }
  const allBelow = id => (below[id] || []).flatMap(c => [c, ...allBelow(c.id)])
  const rows = []
  const walk = (list, depth) => {
    for (const s of list) {
      const children = (below[s.id] || []).length
      const isFolded = children > 0 && !opened.has(s.id)
      const hiddenTabs = isFolded ? allBelow(s.id) : []
      rows.push({ session: s, depth, children, folded: isFolded, hidden: hiddenTabs.length, hiddenTabs })
      if (children > 0 && !isFolded) walk(below[s.id], depth + 1)
    }
  }
  walk(below.__root__ || [], 0)
  return rows
}

export function loadOpened() {
  const saved = lsGet(OPENED_KEY, [])
  return new Set(Array.isArray(saved) ? saved.filter(id => typeof id === 'string') : [])
}

// 畳む / 開くを切り替えた新しい集合を返して覚える。 一覧に居ないタブの id は覚えから落とす (= 閉じたタブの
// 分が溜まらない)。
export function toggleOpened(opened, id, sessions) {
  const next = new Set(opened)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  const ids = new Set(sessions.map(s => s.id))
  const kept = [...next].filter(sid => ids.has(sid))
  lsSet(OPENED_KEY, kept)
  return new Set(kept)
}
