// The conversation list as a folder tree: each tab sits in the folder of the project its agent started in
// (`projects/Platform` and `projects/Platform/subprojects/Client` both -> Platform), under a folder per agent when
// the list holds more than one agent. A subproject gets no folder of its own: it usually holds one tab, so there
// would be nothing to open. Inside a folder, its tabs come first (forks and child tabs under their parent, see
// `sessionTree`), then its subfolders by name. A folded folder hides everything below it and carries the
// most urgent badge of what it hides. Called by the drawer; which folders are folded is kept per device.

import { lsGet, lsSet } from '../../_common/storage.js'
import { sessionTree } from './sessionTree.js'

export const FOLDED_FOLDERS_KEY = 'cpc.drawer.folded-folders'

// A folded folder shows the first of these that any tab inside it has
const BADGE_ORDER = ['pending', 'processing', 'new']

// The folder a tier puts a tab in. A tier is pairs of a container and a name
// (`projects/<name>/subprojects/<name>`); only the first name (= the project) becomes a folder. `normal` and an
// unknown tier stay in the agent's own folder.
export function tierFolders(tier) {
  if (typeof tier !== 'string' || tier === '' || tier === 'normal') return []
  const parts = tier.split('/').filter(Boolean)
  const project = parts.length >= 2 ? parts[1] : parts[0]
  return [project]
}

// The tab at the top of `s`'s line of parents among the listed tabs (= `s` itself when its parent is not listed)
function topParent(s, byId) {
  const seen = new Set()
  let top = s
  while (top.parent_id && byId.has(top.parent_id) && !seen.has(top.id)) {
    seen.add(top.id)
    top = byId.get(top.parent_id)
  }
  return top
}

function newFolder(key, name) {
  return { key, name, sessions: [], folders: new Map() }
}

function mostUrgent(badges) {
  for (const kind of BADGE_ORDER) {
    const found = badges.find(b => b?.kind === kind)
    if (found) return found
  }
  return null
}

// sorted = the tabs in list order (= latest activity first). agents = the configured agents, in the
// order the folders of agents follow. Rows are either
//   { kind: 'folder', key, name, depth, folded, count (= tabs below), badge (= only when folded) }
//   { kind: 'session', session, depth, children, folded, hidden, nested (= under its parent tab) }
export function folderTree(sorted, { agents = [], foldedFolders = new Set(), foldedSessions = new Set(), badges = {} } = {}) {
  const agentIds = new Set(sorted.map(s => s.agent_id))
  const showAgents = agentIds.size > 1
  const byId = new Map(sorted.map(s => [s.id, s]))
  const root = newFolder('', '')
  for (const s of sorted) {
    let folder = root
    // A fork or child tab goes where its parent is, so it always stays under the parent (its own tier may not be
    // read yet, or may differ).
    const placed = topParent(s, byId)
    const agentKey = placed.agent_id || ''
    if (showAgents) {
      const name = agents.find(a => a.id === placed.agent_id)?.display_name || placed.agent_id || '?'
      if (!folder.folders.has(agentKey)) folder.folders.set(agentKey, newFolder(agentKey, name))
      folder = folder.folders.get(agentKey)
    }
    let key = agentKey
    for (const name of tierFolders(placed.tier)) {
      key = `${key}/${name}`
      if (!folder.folders.has(name)) folder.folders.set(name, newFolder(key, name))
      folder = folder.folders.get(name)
    }
    folder.sessions.push(s)
  }

  const agentOrder = id => {
    const at = agents.findIndex(a => a.id === id)
    return at === -1 ? agents.length : at
  }
  const subfolders = (folder, isAgentLevel) => [...folder.folders.entries()]
    .sort(([a, x], [b, y]) => (isAgentLevel ? agentOrder(a) - agentOrder(b) : 0) || x.name.localeCompare(y.name))
    .map(([, f]) => f)
  const tabsBelow = folder => folder.sessions.length
    + [...folder.folders.values()].reduce((n, f) => n + tabsBelow(f), 0)
  const sessionsBelow = folder => [...folder.sessions, ...[...folder.folders.values()].flatMap(sessionsBelow)]

  const rows = []
  const walk = (folder, depth, isAgentLevel) => {
    for (const row of sessionTree(folder.sessions, foldedSessions)) {
      rows.push({ kind: 'session', ...row, depth: depth + row.depth, nested: row.depth > 0 })
    }
    for (const sub of subfolders(folder, isAgentLevel)) {
      const folded = foldedFolders.has(sub.key)
      rows.push({
        kind: 'folder',
        key: sub.key,
        name: sub.name,
        depth,
        folded,
        count: tabsBelow(sub),
        badge: folded ? mostUrgent(sessionsBelow(sub).map(s => badges[s.id])) : null,
      })
      if (!folded) walk(sub, depth + 1, false)
    }
  }
  walk(root, 0, showAgents)
  return rows
}

export function loadFoldedFolders() {
  const saved = lsGet(FOLDED_FOLDERS_KEY, [])
  return new Set(Array.isArray(saved) ? saved.filter(key => typeof key === 'string') : [])
}

// Every folder the tabs make, folded or hidden under a folded one (= the same keys `folderTree` gives)
function folderKeys(sessions) {
  const byId = new Map(sessions.map(s => [s.id, s]))
  const keys = new Set()
  for (const s of sessions) {
    const placed = topParent(s, byId)
    let key = placed.agent_id || ''
    keys.add(key)
    for (const name of tierFolders(placed.tier)) {
      key = `${key}/${name}`
      keys.add(key)
    }
  }
  return keys
}

// Returns the new set with `key` folded or unfolded, and keeps it. Folders no tab is in any more are
// dropped, so closed tiers do not pile up.
export function toggleFoldedFolder(folded, key, sessions) {
  const next = new Set(folded)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  const keys = folderKeys(sessions)
  const kept = [...next].filter(k => keys.has(k))
  lsSet(FOLDED_FOLDERS_KEY, kept)
  return new Set(kept)
}
