// How the folder tree came out, written to the backend's record (= `logs/backend.error.log`, as `drawer:tree` of the
// `sw-log` lines) when the list is opened and when the page comes back to the front. On a screen whose list is not a
// tree, it says which build the screen runs, how many tabs it holds, how many of them carry a tier or the child mark,
// how many agents it knows and whether the backend has answered since the page started, so the cause can be read from
// the record without seeing the screen. Called by SessionDrawer (open) and by useSessions (foreground).
import { runningBuildId } from '../../_common/appUpdate.js'
import { getSnapshot } from '../../state/sessions.js'
import { httpClient } from '../../transport/http.ts'
import { folderTree } from './folderTree.js'

// sessions = the tabs in the state, rows = the rows folderTree made of them. `trigger` is what caused the report
// ('open' = the list was opened, 'foreground' = the page came back to the front).
export function treeReport({ build, sessions, rows, agentCount = 0, serverAnswered = false, trigger = 'open' }) {
  const tiers = {}
  for (const s of sessions) tiers[s.id] = s.tier ?? null
  return {
    stage: 'drawer:tree',
    trigger,
    build,
    sessionCount: sessions.length,
    withTierCount: sessions.filter(s => typeof s.tier === 'string' && s.tier !== '').length,
    childCount: sessions.filter(s => s.child === true).length,
    agentCount,
    serverAnswered,
    folderCount: rows.filter(row => row.kind === 'folder').length,
    tiers,
  }
}

export function sendTreeReport(payload) {
  httpClient.apiFetch('/log/sw', { method: 'POST', jsonBody: payload }).catch(() => {})
}

// Reports the tree the state makes right now, whether or not the list is open (= the rows are built here the way the
// list builds them, from the same state). `serverAnswered` says whether a backend answer has replaced the local copy.
export function sendTreeReportOfState({ serverAnswered, trigger }) {
  const { sessions, agents } = getSnapshot()
  const rows = folderTree(sessions, { agents })
  sendTreeReport(treeReport({ build: runningBuildId(), sessions, rows, agentCount: agents.length, serverAnswered, trigger }))
}
