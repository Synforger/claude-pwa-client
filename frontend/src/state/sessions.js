// session-level 真値 store (= state-trace.md § 5)。 sessions list + activeId + agents + status +
// sessionActivity + unreadDone。 backend SSE / GET の結果を流す入口でもある。

import { createStore } from './_store.js'

const INITIAL = {
  sessions: [],          // SessionDef[] (= domain/Session.ts に準拠)
  activeId: null,        // string | null
  agents: [],            // Agent[] (= 起動時 1 回 GET /agents)
  accounts: [],          // Account[] (= GET /accounts)
  status: {},            // { [sid]: SessionStatus } SSE 由来
  sessionActivity: {},   // { [sid]: { length, ts } } sort 用
  unreadDone: {},        // { [sid]: boolean }
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
export function removeSession(sid) {
  store.setState(prev => {
    const next = prev.sessions.filter(s => s.sid !== sid)
    if (next.length === prev.sessions.length) return prev
    const status = { ...prev.status }; delete status[sid]
    const activity = { ...prev.sessionActivity }; delete activity[sid]
    const unread = { ...prev.unreadDone }; delete unread[sid]
    return { ...prev, sessions: next, status, sessionActivity: activity, unreadDone: unread }
  })
}
export function patchSession(sid, patch) {
  store.setState(prev => {
    const idx = prev.sessions.findIndex(s => s.sid === sid)
    if (idx < 0) return prev
    const next = prev.sessions.slice()
    next[idx] = { ...prev.sessions[idx], ...patch }
    return { ...prev, sessions: next }
  })
}

export function setActiveId(sid) {
  store.setState(prev => prev.activeId === sid ? prev : { ...prev, activeId: sid })
}

export function setAgents(agents) {
  store.setState(prev => ({ ...prev, agents }))
}
export function setAccounts(accounts) {
  store.setState(prev => ({ ...prev, accounts }))
}

export function setStatusFor(sid, status) {
  store.setState(prev => ({ ...prev, status: { ...prev.status, [sid]: status } }))
}
export function applyStatusSnapshot(snapshot) {
  // snapshot = { [sid]: SessionStatus } 全置き換え
  store.setState(prev => ({ ...prev, status: snapshot || {} }))
}

export function setSessionActivity(sid, value) {
  store.setState(prev => ({ ...prev, sessionActivity: { ...prev.sessionActivity, [sid]: value } }))
}

export function setUnreadDone(sid, value) {
  store.setState(prev => ({ ...prev, unreadDone: { ...prev.unreadDone, [sid]: value } }))
}
export function clearUnreadDone(sid) {
  store.setState(prev => {
    if (!(sid in prev.unreadDone)) return prev
    const next = { ...prev.unreadDone }; delete next[sid]
    return { ...prev, unreadDone: next }
  })
}

export function hydrate(partial) {
  if (!partial || typeof partial !== 'object') return
  store.setState(prev => ({ ...prev, ...partial }))
}
