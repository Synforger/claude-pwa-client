// The conversation list as a folder tree: each tab sits in the folder of the tier its agent started in
// (`projects/Platform/subprojects/Client` -> Platform ▸ Client), under a folder per agent when the list holds more
// than one agent. Inside a folder, its tabs come first (forks and child tabs under their parent, see
// `sessionTree`), then its subfolders by name. A folded folder hides everything below it and carries the
// most urgent badge of what it hides. Called by the drawer; which folders are folded is kept per device.

import { lsGet, lsSet } from '../../utils/storage.js'
import { sessionTree } from './sessionTree.js'

export const FOLDED_FOLDERS_KEY = 'cpc.drawer.folded-folders'

// A folded folder shows the first of these that any tab inside it has
const BADGE_ORDER = ['pending', 'processing', 'new']

// The folder names a tier walks through. A tier is pairs of a container and a name
// (`projects/<name>/subprojects/<name>`), so only the names become folders. `normal` and an unknown
// tier stay in the agent's own folder.
export function tierFolders(tier) {
  if (typeof tier !== 'string' || tier === '' || tier === 'normal') return []
  const parts = tier.split('/').filter(Boolean)
  return parts.length % 2 === 0 ? parts.filter((_, i) => i % 2 === 1) : parts
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
  const root = newFolder('', '')
  for (const s of sorted) {
    let folder = root
    const agentKey = s.agent_id || ''
    if (showAgents) {
      const name = agents.find(a => a.id === s.agent_id)?.display_name || s.agent_id || '?'
      if (!folder.folders.has(agentKey)) folder.folders.set(agentKey, newFolder(agentKey, name))
      folder = folder.folders.get(agentKey)
    }
    let key = agentKey
    for (const name of tierFolders(s.tier)) {
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
  const keys = new Set()
  for (const s of sessions) {
    let key = s.agent_id || ''
    keys.add(key)
    for (const name of tierFolders(s.tier)) {
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
