// 会話の一覧の親子の並びと、 畳んだタブの保存の検査。
import { describe, it, expect, beforeEach } from 'vitest'
import { OPENED_KEY, loadOpened, sessionTree, toggleOpened } from '../../../src/features/session-drawer/sessionTree.js'

const store = new Map()
globalThis.localStorage = {
  getItem: (k) => (store.has(k) ? store.get(k) : null),
  setItem: (k, v) => { store.set(k, String(v)) },
  removeItem: (k) => { store.delete(k) },
}

const tab = (id, parent_id = null, child = false) => ({ id, parent_id, child })
// 渡す順 = 一覧の順 (= 最終活動の降順)
const SESSIONS = [tab('a'), tab('a1', 'a', true), tab('b'), tab('a2', 'a'), tab('a1x', 'a1', true), tab('lost', 'gone')]

const shape = rows => rows.map(r => [r.session.id, r.depth, r.children, r.folded, r.hidden])

beforeEach(() => store.clear())

describe('sessionTree', () => {
  it('puts children right under their parent, in the order given', () => {
    expect(shape(sessionTree(SESSIONS, new Set(['a', 'a1'])))).toEqual([
      ['a', 0, 2, false, 0],
      ['a1', 1, 1, false, 0],
      ['a1x', 2, 0, false, 0],
      ['a2', 1, 0, false, 0],
      ['b', 0, 0, false, 0],
      ['lost', 0, 0, false, 0],      // 親が一覧に居ない孤児はトップレベル
    ])
  })

  it('leaves out everything under a folded parent and says how many it hides', () => {
    expect(shape(sessionTree(SESSIONS, new Set()))).toEqual([
      ['a', 0, 2, true, 3],
      ['b', 0, 0, false, 0],
      ['lost', 0, 0, false, 0],
    ])
    expect(shape(sessionTree(SESSIONS, new Set(['a'])))).toEqual([
      ['a', 0, 2, false, 0],
      ['a1', 1, 1, true, 1],
      ['a2', 1, 0, false, 0],
      ['b', 0, 0, false, 0],
      ['lost', 0, 0, false, 0],
    ])
  })

  it('does not count a tab with nothing under it as folded', () => {
    expect(shape(sessionTree(SESSIONS, new Set(['a', 'a1'])))[4]).toEqual(['b', 0, 0, false, 0])
  })
})

describe('folded tabs are kept per device', () => {
  it('starts with nothing opened', () => {
    expect(loadOpened()).toEqual(new Set())
  })

  it('remembers an opened parent and forgets tabs that are no longer listed', () => {
    let opened = toggleOpened(new Set(['closed']), 'a', SESSIONS)
    expect(opened).toEqual(new Set(['a']))
    expect(JSON.parse(localStorage.getItem(OPENED_KEY))).toEqual(['a'])
    expect(loadOpened()).toEqual(new Set(['a']))
    opened = toggleOpened(opened, 'a', SESSIONS)
    expect(loadOpened()).toEqual(new Set())
  })

  it('starts from scratch on a device that kept the folded tabs of an older build', () => {
    localStorage.setItem('cpc.drawer.folded', '["a"]')
    expect(loadOpened()).toEqual(new Set())
  })

  it('reads a broken record as nothing opened', () => {
    localStorage.setItem(OPENED_KEY, '{"a": 1}')
    expect(loadOpened()).toEqual(new Set())
    localStorage.setItem(OPENED_KEY, '[1, "a"]')
    expect(loadOpened()).toEqual(new Set(['a']))
  })
})
