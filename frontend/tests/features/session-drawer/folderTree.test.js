// The conversation list as a folder tree of tiers, and how folded folders are kept.
import { describe, it, expect, beforeEach } from 'vitest'
import { FOLDED_FOLDERS_KEY, folderTree, loadFoldedFolders, tierFolders, toggleFoldedFolder } from '../../../src/features/session-drawer/folderTree.js'

const store = new Map()
globalThis.localStorage = {
  getItem: (k) => (store.has(k) ? store.get(k) : null),
  setItem: (k, v) => { store.set(k, String(v)) },
  removeItem: (k) => { store.delete(k) },
}

const tab = (id, tier, { agent = 'main', parent = null } = {}) => ({ id, tier, agent_id: agent, parent_id: parent })
const AGENTS = [{ id: 'main', display_name: 'Main' }, { id: 'helper', display_name: 'Helper' }]
const Platform = 'projects/Platform'
const CLIENT = 'projects/Platform/subprojects/Client'
const SLIDES = 'projects/Platform/subprojects/Slides'
// in list order (= latest activity first)
const ONE_AGENT = [
  tab('client', CLIENT),
  tab('top', 'normal'),
  tab('slides', SLIDES),
  tab('child', CLIENT, { parent: 'client' }),
  tab('ap', Platform),
  tab('unknown', null),
]

const shape = rows => rows.map(r => (r.kind === 'folder'
  ? ['folder', r.key, r.depth, r.folded, r.count]
  : [r.session.id, r.depth, r.nested]))

beforeEach(() => store.clear())

describe('tierFolders', () => {
  it('turns the names of a tier into folders, and leaves normal and unknown tiers in the agent folder', () => {
    expect(tierFolders(CLIENT)).toEqual(['Platform'])        // a subproject gets no folder of its own
    expect(tierFolders(Platform)).toEqual(['Platform'])
    expect(tierFolders('normal')).toEqual([])
    expect(tierFolders(null)).toEqual([])
    expect(tierFolders('')).toEqual([])
  })
})

describe('folderTree', () => {
  it('puts each tab in the folder of its project, subprojects included, in list order', () => {
    expect(shape(folderTree(ONE_AGENT, { agents: AGENTS }))).toEqual([
      ['top', 0, false],
      ['unknown', 0, false],
      ['folder', 'main/Platform', 0, false, 4],
      ['client', 1, false],
      ['child', 2, true],          // a child tab stays under its parent, one step further in
      ['slides', 1, false],
      ['ap', 1, false],
    ])
  })

  it('keeps a fork or child tab under its parent even when its own tier is unknown or different', () => {
    const tabs = [tab('client', CLIENT), tab('fork', null, { parent: 'client' }), tab('child', 'normal', { parent: 'fork' })]
    expect(shape(folderTree(tabs, { agents: AGENTS }))).toEqual([
      ['folder', 'main/Platform', 0, false, 3],
      ['client', 1, false],
      ['fork', 2, true],
      ['child', 3, true],
    ])
  })

  it('adds a folder per agent, in the order the agents are configured, when the list holds more than one', () => {
    const tabs = [tab('helper-top', 'normal', { agent: 'helper' }), ...ONE_AGENT.slice(0, 2)]
    expect(shape(folderTree(tabs, { agents: AGENTS }))).toEqual([
      ['folder', 'main', 0, false, 2],
      ['top', 1, false],
      ['folder', 'main/Platform', 1, false, 1],
      ['client', 2, false],
      ['folder', 'helper', 0, false, 1],
      ['helper-top', 1, false],
    ])
    expect(folderTree(tabs, { agents: AGENTS })[0].name).toBe('Main')
  })

  it('hides everything below a folded folder and says how many tabs it holds', () => {
    expect(shape(folderTree(ONE_AGENT, { agents: AGENTS, foldedFolders: new Set(['main/Platform']) }))).toEqual([
      ['top', 0, false],
      ['unknown', 0, false],
      ['folder', 'main/Platform', 0, true, 4],
    ])
  })

  it('carries the most urgent badge of the tabs a folded folder hides, and none when open', () => {
    const badges = { slides: { kind: 'new', label: '●' }, child: { kind: 'pending', label: '?' } }
    const folded = folderTree(ONE_AGENT, { agents: AGENTS, foldedFolders: new Set(['main/Platform']), badges })
    expect(folded.find(r => r.key === 'main/Platform').badge).toEqual({ kind: 'pending', label: '?' })
    const open = folderTree(ONE_AGENT, { agents: AGENTS, badges })
    expect(open.find(r => r.key === 'main/Platform').badge).toBeNull()
  })

  it('puts the tabs of an agent with list_folder in that folder, under the agent the folder names', () => {
    const agents = [...AGENTS, { id: 'head', display_name: 'Head', list_folder: 'main/Platform/Heads' }]
    const tabs = [tab('h1', 'normal', { agent: 'head' }), tab('ap', Platform), tab('h2', null, { agent: 'head' })]
    // one agent folder only: the head tabs sit in main's folders, so the list holds main alone
    expect(shape(folderTree(tabs, { agents }))).toEqual([
      ['folder', 'main/Platform', 0, false, 3],
      ['ap', 1, false],
      ['folder', 'main/Platform/Heads', 1, false, 2],
      ['h1', 2, false],
      ['h2', 2, false],
    ])
    // folding the project folds the heads with it
    expect(shape(folderTree(tabs, { agents, foldedFolders: new Set(['main/Platform']) }))).toEqual([
      ['folder', 'main/Platform', 0, true, 3],
    ])
  })

  it('shows the agent folder list_folder names even when that agent has no tab of its own', () => {
    const agents = [...AGENTS, { id: 'head', display_name: 'Head', list_folder: 'helper/Heads' }]
    const tabs = [tab('top', 'normal'), tab('h1', 'normal', { agent: 'head' })]
    const rows = folderTree(tabs, { agents })
    expect(shape(rows)).toEqual([
      ['folder', 'main', 0, false, 1],
      ['top', 1, false],
      ['folder', 'helper', 0, false, 1],
      ['folder', 'helper/Heads', 1, false, 1],
      ['h1', 2, false],
    ])
    expect(rows.find(r => r.key === 'helper').name).toBe('Helper')
  })

  it('puts a tab with its own list_folder there, ahead of its agent\'s, so tabs of one agent split into folders', () => {
    const agents = [...AGENTS, { id: 'head', display_name: 'Head', list_folder: 'main/Game/Heads' }]
    const tabs = [
      { ...tab('narrator', null, { agent: 'head' }), list_folder: 'main/Game/World A' },
      { ...tab('judge', null, { agent: 'head' }), list_folder: 'main/Game/Measure' },
      tab('old', null, { agent: 'head' }),
      { ...tab('bad', null, { agent: 'head' }), list_folder: 'main' },
    ]
    expect(shape(folderTree(tabs, { agents }))).toEqual([
      ['folder', 'main/Game', 0, false, 4],
      ['folder', 'main/Game/Heads', 1, false, 2],
      ['old', 2, false],
      ['bad', 2, false],
      ['folder', 'main/Game/Measure', 1, false, 1],
      ['judge', 2, false],
      ['folder', 'main/Game/World A', 1, false, 1],
      ['narrator', 2, false],
    ])
  })

  it('keeps an agent in its own folder when its list_folder is not a usable path', () => {
    for (const listFolder of ['', 'main', 'main//Heads', ' / ', 42]) {
      const agents = [...AGENTS, { id: 'head', display_name: 'Head', list_folder: listFolder }]
      const rows = folderTree([tab('top', 'normal'), tab('h1', 'normal', { agent: 'head' })], { agents })
      expect(rows.filter(r => r.kind === 'folder').map(r => r.key)).toEqual(['main', 'head'])
    }
  })

  it('folds a parent tab inside a folder as before', () => {
    const rows = folderTree(ONE_AGENT, { agents: AGENTS, foldedSessions: new Set(['client']) })
    const client = rows.find(r => r.session?.id === 'client')
    expect([client.folded, client.hidden]).toEqual([true, 1])
    expect(rows.some(r => r.session?.id === 'child')).toBe(false)
  })
})

describe('folded folders are kept per device', () => {
  it('saves a fold and reads it back', () => {
    const next = toggleFoldedFolder(new Set(), 'main/Platform', ONE_AGENT)
    expect([...next]).toEqual(['main/Platform'])
    expect(JSON.parse(store.get(FOLDED_FOLDERS_KEY))).toEqual(['main/Platform'])
    expect([...loadFoldedFolders()]).toEqual(['main/Platform'])
    expect([...toggleFoldedFolder(next, 'main/Platform', ONE_AGENT)]).toEqual([])
  })

  it('keeps the fold of a folder hidden under a folded one, and drops folders no tab is in', () => {
    const tabs = [tab('helper-top', 'normal', { agent: 'helper' }), ...ONE_AGENT]
    const next = toggleFoldedFolder(new Set(['main/Platform', 'main/Gone']), 'main', tabs)
    expect([...next].sort()).toEqual(['main', 'main/Platform'])
  })

  it('keeps the fold of a folder only list_folder makes', () => {
    const agents = [...AGENTS, { id: 'head', display_name: 'Head', list_folder: 'main/Platform/Heads' }]
    const tabs = [tab('h1', 'normal', { agent: 'head' })]
    expect([...toggleFoldedFolder(new Set(), 'main/Platform/Heads', tabs, agents)]).toEqual(['main/Platform/Heads'])
    // without the agents the folder is not known, so the fold is dropped as a folder no tab is in
    expect([...toggleFoldedFolder(new Set(), 'main/Platform/Heads', tabs)]).toEqual([])
  })

  it('reads a broken saved value as nothing folded', () => {
    store.set(FOLDED_FOLDERS_KEY, '{"not":"a list"}')
    expect([...loadFoldedFolders()]).toEqual([])
  })
})
