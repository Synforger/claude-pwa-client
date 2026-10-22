// タブの一覧の突き合わせの判定。 useSessions の取り直し (= reconcileSessionIds) が呼ぶ。

/**
 * 一覧の概要の snapshot に載るタブの id の集まりが、 手元の一覧の id の集まりと同じか。
 * 並びは問わない (= 一覧は作った順で並べ直すので、 集まりだけを比べる)。
 * @param {string[]} snapshotIds
 * @param {{id: string}[]} sessions
 * @returns {boolean}
 */
export function sameSessionIds(snapshotIds, sessions) {
  const mine = new Set(sessions.map(s => s.id))
  const theirs = new Set(snapshotIds)
  if (mine.size !== theirs.size) return false
  for (const id of theirs) {
    if (!mine.has(id)) return false
  }
  return true
}
