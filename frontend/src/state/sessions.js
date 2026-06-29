// session-level 真値 store (= state-trace.md § 5)。 sessions list + activeId + agents + status +
// sessionActivity + unreadDone。 backend SSE / GET の結果を流す入口でもある。
//
// 識別キーは `id` で統一 (= 2026-06-29 Phase J-1、 ADR-026 末尾「将来 task」 1 件目)。
// backend response の Session shape は `.id` を持つ (= SessionDrawer / domain consumer 全件と
// 一致)。 旧実装は `.sid` で内部 filter していたため `removeSession` / `patchSession` の
// 直呼出が事実上 no-op で dead code 化していた。 本 file の setter は全て `.id` を真値とする。

import { createStore } from './_store.js'

const INITIAL = {
  sessions: [],          // SessionDef[] (= domain/Session.ts に準拠、 runtime は `.id` キー)
  activeId: null,        // string | null
  agents: [],            // Agent[] (= 起動時 1 回 GET /agents)
  accounts: [],          // Account[] (= GET /accounts)
  status: {},            // { [id]: SessionStatus } SSE 由来
  sessionActivity: {},   // { [id]: { length, ts } } sort 用
  unreadDone: {},        // { [id]: boolean }
}

const store = createStore(INITIAL, { name: 'sessions' })

export const getSnapshot = () => store.getSnapshot()
export const subscribe = (listener) => store.subscribe(listener)

export function setSessions(sessions) {
  store.setState(prev => ({ ...prev, sessions }))
}
export function appendSession(session) {
  store.setState(prev => ({ ...prev, sessions: [session, ...prev.sessions] }))
}
export function removeSession(id) {
  store.setState(prev => {
    const next = prev.sessions.filter(s => s.id !== id)
    if (next.length === prev.sessions.length) return prev
    const status = { ...prev.status }; delete status[id]
    const activity = { ...prev.sessionActivity }; delete activity[id]
    const unread = { ...prev.unreadDone }; delete unread[id]
    return { ...prev, sessions: next, status, sessionActivity: activity, unreadDone: unread }
  })
}
export function patchSession(id, patch) {
  store.setState(prev => {
    const idx = prev.sessions.findIndex(s => s.id === id)
    if (idx < 0) return prev
    const next = prev.sessions.slice()
    next[idx] = { ...prev.sessions[idx], ...patch }
    return { ...prev, sessions: next }
  })
}

export function setActiveId(id) {
  store.setState(prev => prev.activeId === id ? prev : { ...prev, activeId: id })
}

export function setAgents(agents) {
  store.setState(prev => ({ ...prev, agents }))
}
export function setAccounts(accounts) {
  store.setState(prev => ({ ...prev, accounts }))
}

export function setStatusFor(id, status) {
  store.setState(prev => ({ ...prev, status: { ...prev.status, [id]: status } }))
}
export function applyStatusSnapshot(snapshot) {
  // snapshot = { [id]: SessionStatus } 全置き換え
  store.setState(prev => ({ ...prev, status: snapshot || {} }))
}

export function setSessionActivity(id, value) {
  store.setState(prev => ({ ...prev, sessionActivity: { ...prev.sessionActivity, [id]: value } }))
}

export function setUnreadDone(id, value) {
  store.setState(prev => ({ ...prev, unreadDone: { ...prev.unreadDone, [id]: value } }))
}
export function clearUnreadDone(id) {
  store.setState(prev => {
    if (!(id in prev.unreadDone)) return prev
    const next = { ...prev.unreadDone }; delete next[id]
    return { ...prev, unreadDone: next }
  })
}

export function hydrate(partial) {
  if (!partial || typeof partial !== 'object') return
  store.setState(prev => ({ ...prev, ...partial }))
}
