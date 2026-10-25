// 一覧を開いた時の、 folder の木の組み上がりを backend の記録へ 1 行残す (= logs/backend.error.log の
// `sw-log` の `drawer:tree`)。 一覧が木にならない画面で、 その画面がどの build か、 タブの階層を
// 何本受け取っているか、 木の行が何本組めたかを、 画面を見ずに記録から決めるため。 呼び手は SessionDrawer。
import { httpClient } from '../../transport/http.ts'

// sessions = 状態の中のタブ、 rows = folderTree が組んだ行
export function treeReport({ build, sessions, rows }) {
  const tiers = {}
  for (const s of sessions) tiers[s.id] = s.tier ?? null
  return {
    stage: 'drawer:tree',
    build,
    sessionCount: sessions.length,
    withTierCount: sessions.filter(s => typeof s.tier === 'string' && s.tier !== '').length,
    folderCount: rows.filter(row => row.kind === 'folder').length,
    tiers,
  }
}

export function sendTreeReport(payload) {
  httpClient.apiFetch('/log/sw', { method: 'POST', jsonBody: payload }).catch(() => {})
}
