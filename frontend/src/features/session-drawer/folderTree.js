// The conversation list as a folder tree: each tab sits in the folder of the project its agent started in
// (`projects/Platform` and `projects/Platform/subprojects/Client` both -> Platform), under a folder per agent when
// the list holds more than one agent. A subproject gets no folder of its own: it usually holds one tab, so there
// would be nothing to open. Inside a folder, its tabs come first (forks and child tabs under their parent, see
// `sessionTree`), then its subfolders by name. The folder of an agent starts open, and every folder below it and
// every parent tab starts folded. A folded folder or parent hides everything below it and carries the most urgent
// badge of what it hides. An agent with `list_folder` (`<agent id>/<folder>/...`) puts its tabs in that
// folder instead of its own, so the tabs of several agents that serve one project fold together; a tab with its own
// `list_folder` (set by whoever made it) goes there ahead of its agent's, so tabs of one agent can sit in different
// folders. Called by the drawer; which folders were switched from how they start is kept per device.

import { lsGet, lsSet } from '../../_common/storage.js'
import { sessionTree } from './sessionTree.js'

export const TOGGLED_FOLDERS_KEY = 'cpc.drawer.toggled-folders'

// A folded folder or parent shows the first of these that any tab it stands for has
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

// The names of `list_folder` (`<agent id>/<folder>/...`) of an agent or a tab, or none when it has no usable one
export function listFolder(owner) {
  if (typeof owner?.list_folder !== 'string') return []
  const names = owner.list_folder.split('/').map(name => name.trim())
  return names.length >= 2 && names.every(Boolean) ? names : []
}

// Where `placed` (= the top of its line of parents) sits: the agent whose folder holds it, and the folders below
// that agent's folder (the tab's own `list_folder`, else its agent's, then the project of its tier)
function placement(placed, agentsById) {
  const own = listFolder(placed)
  const [agentKey, ...folders] = own.length ? own : listFolder(agentsById.get(placed.agent_id))
  if (agentKey) return { agentKey, folders: [...folders, ...tierFolders(placed.tier)] }
  return { agentKey: placed.agent_id || '', folders: tierFolders(placed.tier) }
}

function newFolder(key, name) {
  return { key, name, sessions: [], folders: new Map() }
}

// The key of an agent's folder is the agent's id alone; a folder below it adds `/<name>`. So the key says how the
// folder starts, and a folder no one has touched needs no entry.
function isFolderFolded(key, toggled) {
  const startsFolded = key.includes('/')
  return toggled.has(key) ? !startsFolded : startsFolded
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
//   { kind: 'session', session, depth, children, folded, hidden, nested (= under its parent tab),
//     badge (= when folded, the most urgent of its own and those it hides) }
export function folderTree(sorted, { agents = [], toggledFolders = new Set(), openedSessions = new Set(), badges = {} } = {}) {
  const agentsById = new Map(agents.map(a => [a.id, a]))
  const byId = new Map(sorted.map(s => [s.id, s]))
  // A fork or child tab goes where its parent is, so it always stays under the parent (its own tier may not be
  // read yet, or may differ).
  const placed = sorted.map(s => [s, placement(topParent(s, byId), agentsById)])
  const showAgents = new Set(placed.map(([, at]) => at.agentKey)).size > 1
  const root = newFolder('', '')
  for (const [s, { agentKey, folders }] of placed) {
    let folder = root
    if (showAgents) {
      const name = agentsById.get(agentKey)?.display_name || agentKey || '?'
      if (!folder.folders.has(agentKey)) folder.folders.set(agentKey, newFolder(agentKey, name))
      folder = folder.folders.get(agentKey)
    }
    let key = agentKey
    for (const name of folders) {
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
    for (const row of sessionTree(folder.sessions, openedSessions)) {
      const badge = mostUrgent([row.session, ...row.hiddenTabs].map(s => badges[s.id]))
      rows.push({ kind: 'session', ...row, depth: depth + row.depth, nested: row.depth > 0, badge })
    }
    for (const sub of subfolders(folder, isAgentLevel)) {
      const folded = isFolderFolded(sub.key, toggledFolders)
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

export function loadToggledFolders() {
  const saved = lsGet(TOGGLED_FOLDERS_KEY, [])
  return new Set(Array.isArray(saved) ? saved.filter(key => typeof key === 'string') : [])
}

// Every folder the tabs make, folded or hidden under a folded one (= the same keys `folderTree` gives)
function folderKeys(sessions, agents) {
  const agentsById = new Map(agents.map(a => [a.id, a]))
  const byId = new Map(sessions.map(s => [s.id, s]))
  const keys = new Set()
  for (const s of sessions) {
    const { agentKey, folders } = placement(topParent(s, byId), agentsById)
    let key = agentKey
    keys.add(key)
    for (const name of folders) {
      key = `${key}/${name}`
      keys.add(key)
    }
  }
  return keys
}

// Returns the new set with `key` switched, and keeps it. Folders no tab is in any more are dropped, so closed
// tiers do not pile up.
export function toggleFolder(toggled, key, sessions, agents = []) {
  const next = new Set(toggled)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  const keys = folderKeys(sessions, agents)
  const kept = [...next].filter(k => keys.has(k))
  lsSet(TOGGLED_FOLDERS_KEY, kept)
  return new Set(kept)
}
